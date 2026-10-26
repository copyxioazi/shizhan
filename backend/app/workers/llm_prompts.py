"""LLM 角色提示词、输出 Schema 与结果校验。

所有 LLM 输出都必须经过 Pydantic 校验；不合法的输出视为本轮 LLM 失败，
由调用方降级到规则引擎。
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from app.rule_engine import Finding

SAFE_VERIFY_RE = re.compile(
    r"^python(?:3)?(?:\s+-B)?\s+/src/verify/[A-Za-z0-9_./-]+\.py$"
)
MAX_CODE_FINDINGS = 30
MAX_PROMPT_CHARS = 60000
MAX_FILE_CHARS = 12000
MAX_PROMPT_FILES = 40


class LLMValidationError(Exception):
    pass


class GeneralPlan(BaseModel):
    focus_areas: list[str] = Field(min_length=1)
    file_globs: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    risk_hypotheses: list[str] = Field(default_factory=list)


class VulnerabilityCandidate(BaseModel):
    vuln_title: str = Field(min_length=1, max_length=255)
    risk_level: Literal["critical", "high", "medium", "low", "info"]
    file_path: str = Field(min_length=1, max_length=1024)
    line_no: int | None = Field(default=None, ge=1)
    impact_text: str = Field(min_length=1)
    condition_text: str = Field(min_length=1)
    evidence_text: str = Field(min_length=1)
    reproduce_steps_text: str = ""
    verify_code_text: str | None = None


class VerificationDecision(BaseModel):
    vuln_code: str
    action: Literal["execute", "skip"]
    verify_code_text: str | None = None
    reason: str = ""


class LLMAttackPathItem(BaseModel):
    vuln_code: str
    step_order: int = Field(ge=1)
    step_text: str = Field(min_length=1)


class LLMAttackPath(BaseModel):
    path_title: str = Field(min_length=1, max_length=255)
    path_summary: str = Field(min_length=1)
    final_impact_text: str = Field(min_length=1)
    items: list[LLMAttackPathItem] = Field(min_length=1)


class ReportOutput(BaseModel):
    attack_paths: list[LLMAttackPath] = Field(default_factory=list)
    remediation: list[str] = Field(default_factory=list)


def _system(role: str, responsibility: str) -> str:
    return (
        f"你是自动化安全评估系统的 {role} 角色。{responsibility}\n"
        "你必须只输出一个合法 JSON，不要输出 Markdown 代码块、解释或额外文本。"
        "所有文件路径必须是相对源码根目录的 POSIX 路径，不得包含主机绝对路径。"
        "不得编造源码中不存在的文件和行号。"
    )


def general_messages(task_content: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": _system(
                "general（通用处理）",
                "负责理解任务说明，制定分析计划。",
            )
            + "\n输出结构："
            '{"focus_areas":["..."],"file_globs":["**/*.py"],'
            '"keywords":["..."],"risk_hypotheses":["..."]}',
        },
        {
            "role": "user",
            "content": f"评估任务说明：\n{task_content}\n\n请给出分析计划 JSON。",
        },
    ]


def code_analysis_messages(
    task_content: str, files: list[tuple[str, str]]
) -> list[dict[str, str]]:
    analysis_files = [(path, content) for path, content in files if not path.startswith("verify/")]
    verify_scripts = [path for path, _ in files if path.startswith("verify/")]

    chunks: list[str] = []
    used = 0
    truncated = False
    for path, content in analysis_files:
        if len(chunks) >= MAX_PROMPT_FILES or used >= MAX_PROMPT_CHARS:
            truncated = True
            break
        snippet = content[:MAX_FILE_CHARS]
        block = f"### FILE: {path}\n{snippet}"
        chunks.append(block)
        used += len(block)
    if truncated:
        chunks.append("### 注意：源码内容已截断，仅分析以上片段。")

    verify_hint = (
        "可用验证脚本（如果漏洞适用，verify_code_text 只能引用其中之一）：\n"
        + "\n".join(f"- {path}" for path in verify_scripts)
        if verify_scripts
        else "没有可用的 /src/verify 脚本；verify_code_text 请留空。"
    )

    user = (
        f"评估任务说明：\n{task_content}\n\n"
        f"{verify_hint}\n\n"
        "请分析以下源码片段，找出真实存在的安全漏洞。最多返回 20 条，按风险从高到低。\n"
        "每个漏洞对象字段：vuln_title, risk_level（critical/high/medium/low/info）, "
        "file_path, line_no, impact_text, condition_text, evidence_text, "
        "reproduce_steps_text, verify_code_text。\n"
        "evidence_text 必须包含源码中的真实行片段；line_no 必须是该片段在文件中的行号。\n"
        "只输出 JSON 数组。\n\n"
        + "\n\n".join(chunks)
    )
    return [
        {
            "role": "system",
            "content": _system(
                "code_analyst（代码分析）",
                "负责识别 SQL 注入、命令注入、路径穿越、越权访问与硬编码密钥等漏洞。",
            ),
        },
        {"role": "user", "content": user},
    ]


def verification_messages(
    pending: list[dict[str, Any]], verify_scripts: list[str] | None = None
) -> list[dict[str, str]]:
    lines = []
    for item in pending:
        lines.append(
            f"- {item['vuln_code']} | {item['vuln_title']} | {item['file_path']} | "
            f"现有验证命令：{item.get('verify_code_text') or '无'}"
        )
    scripts = [path for path in (verify_scripts or []) if path]
    if scripts:
        script_hint = (
            "可用验证脚本（verify_code_text 只能引用其中之一，不能引用列表外的脚本）：\n"
            + "\n".join(f"- {path}" for path in scripts)
        )
    else:
        script_hint = "没有可用的 /src/verify 脚本；所有漏洞都选择 skip。"
    user = (
        "请为下列漏洞制定验证策略。只允许使用 /src/verify 下已有的 Python 脚本执行验证；"
        "漏洞类型与脚本名匹配时优先 execute，没有合适脚本时选择 skip。\n"
        f"{script_hint}\n"
        "输出 JSON 数组，每个元素：{vuln_code, action: execute|skip, "
        "verify_code_text, reason}。execute 时 verify_code_text 必须形如 "
        "`python -B /src/verify/xxx.py`。\n\n" + "\n".join(lines)
    )
    return [
        {
            "role": "system",
            "content": _system(
                "vuln_verifier（漏洞验证）",
                "负责选择验证策略；不能访问网络，不能修改 /src。",
            ),
        },
        {"role": "user", "content": user},
    ]


def verification_retry_messages(
    pending: list[dict[str, Any]], verify_scripts: list[str] | None = None
) -> list[dict[str, str]]:
    lines = []
    for item in pending:
        evidence = " ".join(str(item.get("evidence_text") or "").split())[-600:]
        lines.append(
            f"- {item['vuln_code']} | {item['vuln_title']} | {item['file_path']} | "
            f"上次命令：{item.get('verify_code_text') or '无'} | "
            f"失败证据：{evidence or '无'}"
        )
    scripts = [path for path in (verify_scripts or []) if path]
    if scripts:
        script_hint = (
            "可用验证脚本（verify_code_text 只能引用其中之一）：\n"
            + "\n".join(f"- {path}" for path in scripts)
        )
    else:
        script_hint = "没有可用的 /src/verify 脚本；所有漏洞都选择 skip。"
    user = (
        "以下漏洞在上一轮验证中失败。请分析失败证据，选择与上次不同的验证脚本重新验证；"
        "如果没有更合适的脚本或失败原因不可恢复，选择 skip。\n"
        f"{script_hint}\n"
        "输出 JSON 数组，每个元素：{vuln_code, action: execute|skip, "
        "verify_code_text, reason}。execute 时 verify_code_text 必须形如 "
        "`python -B /src/verify/xxx.py`。\n\n" + "\n".join(lines)
    )
    return [
        {
            "role": "system",
            "content": _system(
                "vuln_verifier（漏洞验证重规划）",
                "负责根据失败证据调整验证策略；不能访问网络，不能修改 /src。",
            ),
        },
        {"role": "user", "content": user},
    ]


def report_messages(
    project_name: str,
    task_content: str,
    verified: list[dict[str, Any]],
) -> list[dict[str, str]]:
    lines = [
        f"- {item['vuln_code']} | {item['vuln_title']} | {item['risk_level']} | "
        f"{item['file_path']} | 触发条件：{item['condition_text'][:200]}"
        for item in verified
    ]
    user = (
        f"项目：{project_name}\n任务说明：{task_content}\n"
        f"已验证漏洞：\n" + ("\n".join(lines) if lines else "无") + "\n\n"
        "请生成攻击路径和修复建议。输出 JSON 对象："
        '{"attack_paths":[{"path_title":"...","path_summary":"...",'
        '"final_impact_text":"...","items":[{"vuln_code":"VULN-001",'
        '"step_order":1,"step_text":"..."}]}],'
        '"remediation":["按风险从高到低的修复建议"]}。\n'
        "攻击路径只能使用上面列出的 vuln_code；没有可用漏洞时 attack_paths 返回空数组。"
    )
    return [
        {
            "role": "system",
            "content": _system(
                "report_writer（报告整理）",
                "负责基于已验证漏洞整理攻击路径与修复建议。",
            ),
        },
        {"role": "user", "content": user},
    ]


def parse_general_plan(data: Any) -> dict[str, Any]:
    try:
        plan = GeneralPlan.model_validate(data)
    except ValidationError as exc:
        raise LLMValidationError(f"general 输出不符合 Schema：{exc.errors()[:2]}") from exc
    return plan.model_dump()


def _normalise_path(path: str) -> str:
    normalised = path.replace("\\", "/")
    while normalised.startswith("./"):
        normalised = normalised[2:]
    if normalised.startswith("/") or ".." in normalised.split("/"):
        raise LLMValidationError(f"非法文件路径：{path}")
    return normalised


def _ground_evidence(
    file_path: str, content: str, evidence: str, line_no: int | None
) -> tuple[int, str] | None:
    lines = content.splitlines()
    evidence_fragments = [
        fragment.strip()
        for fragment in evidence.replace("\r", "\n").splitlines()
        if len(fragment.strip()) >= 8
    ]
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if any(fragment in stripped or stripped in fragment for fragment in evidence_fragments):
            return index, stripped
    if line_no is not None and 1 <= line_no <= len(lines):
        stripped = lines[line_no - 1].strip()
        if stripped:
            return line_no, stripped
    return None


def _safe_verify_command(value: str | None) -> str | None:
    command = (value or "").strip()
    if command and SAFE_VERIFY_RE.fullmatch(command):
        return command
    return None


def parse_code_findings(
    data: Any, files: list[tuple[str, str]]
) -> list[Finding]:
    if not isinstance(data, list):
        raise LLMValidationError("code_analyst 输出必须是 JSON 数组")
    try:
        candidates = TypeAdapter(list[VulnerabilityCandidate]).validate_python(data)
    except ValidationError as exc:
        raise LLMValidationError(
            f"code_analyst 输出不符合 Schema：{exc.errors()[:2]}"
        ) from exc

    file_map = dict(files)
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates[:MAX_CODE_FINDINGS]:
        try:
            file_path = _normalise_path(candidate.file_path)
        except LLMValidationError:
            # 单个非法路径只丢弃该候选，不影响其它候选
            continue
        content = file_map.get(file_path)
        if content is None:
            continue
        grounded = _ground_evidence(
            file_path, content, candidate.evidence_text, candidate.line_no
        )
        if grounded is None:
            continue
        line_no, line_text = grounded
        key = (file_path, candidate.vuln_title)
        if key in seen:
            continue
        seen.add(key)
        findings.append(
            Finding(
                category="llm",
                vuln_title=candidate.vuln_title[:255],
                risk_level=candidate.risk_level,
                file_path=file_path,
                line_no=line_no,
                impact_text=candidate.impact_text,
                condition_text=candidate.condition_text,
                evidence_text=f"{file_path}:{line_no}: {line_text[:300]}",
                reproduce_steps_text=(
                    candidate.reproduce_steps_text
                    or "1. 启动目标项目\n2. 按触发条件构造请求\n3. 观察返回结果。"
                ),
                verify_code_text=_safe_verify_command(candidate.verify_code_text),
            )
        )
    return findings


def parse_verification_plan(
    data: Any, allowed_codes: set[str]
) -> dict[str, VerificationDecision]:
    if not isinstance(data, list):
        raise LLMValidationError("vuln_verifier 输出必须是 JSON 数组")
    try:
        decisions = TypeAdapter(list[VerificationDecision]).validate_python(data)
    except ValidationError as exc:
        raise LLMValidationError(
            f"vuln_verifier 输出不符合 Schema：{exc.errors()[:2]}"
        ) from exc
    result: dict[str, VerificationDecision] = {}
    for decision in decisions:
        if decision.vuln_code not in allowed_codes:
            continue
        if decision.action == "execute":
            decision.verify_code_text = _safe_verify_command(decision.verify_code_text)
            if decision.verify_code_text is None:
                decision.action = "skip"
                decision.reason = "验证命令不在允许的 /src/verify 范围内"
        result[decision.vuln_code] = decision
    return result


def parse_report_output(
    data: Any, verified_codes: set[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        output = ReportOutput.model_validate(data)
    except ValidationError as exc:
        raise LLMValidationError(
            f"report_writer 输出不符合 Schema：{exc.errors()[:2]}"
        ) from exc

    paths: list[dict[str, Any]] = []
    for path in output.attack_paths[:5]:
        items = [item for item in path.items if item.vuln_code in verified_codes]
        if not items:
            continue
        items.sort(key=lambda item: item.step_order)
        paths.append(
            {
                "path_title": path.path_title[:255],
                "path_summary": path.path_summary,
                "final_impact_text": path.final_impact_text,
                "items": [
                    {
                        "vuln_code": item.vuln_code,
                        "step_order": index,
                        "step_text": item.step_text,
                    }
                    for index, item in enumerate(items, start=1)
                ],
            }
        )
    remediation = [line.strip() for line in output.remediation if line.strip()][:10]
    return paths, remediation
