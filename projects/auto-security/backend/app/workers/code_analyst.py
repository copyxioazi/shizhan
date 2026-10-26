"""代码分析角色：遍历源码、规则检测、漏洞落库。"""

from __future__ import annotations

import json
import re

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models import Vulnerability
from app.rule_engine import scan_files
from app.sandbox.manager import SandboxUnavailable
from app.services.llm_runtime import LLMUnavailable
from app.services.monitor_service import add_chat, add_log
from app.services.vulnerability_service import save_findings
from app.workers.base import WorkerContext, WorkerError
from app.workers.llm_prompts import (
    LLMValidationError,
    code_analysis_messages,
    parse_code_findings,
)
from app.workers.llm_support import announce_fallback, announce_llm_output_invalid
from app.workers.react_analysis import run_react_analysis

MAX_READ_FILES = 300
MAX_SEARCH_KEYWORDS = 12
MAX_TOTAL_SEARCH_HITS = 1000
BUILTIN_SEARCH_KEYWORDS = (
    "sql",
    "execute",
    "os.system",
    "subprocess",
    "open(",
    "secret",
    "password",
    "token",
)
TASK_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.()]{2,}")


def build_search_keywords(task_content: str) -> list[str]:
    """任务说明中的词项 + 内置安全关键字（FR-EXEC-03）。"""
    keywords = list(BUILTIN_SEARCH_KEYWORDS)
    for match in TASK_TOKEN_RE.finditer(task_content):
        token = match.group(0).lower()
        if token not in keywords:
            keywords.append(token)
    return keywords[:MAX_SEARCH_KEYWORDS]


async def _keyword_search(ctx: WorkerContext, keywords: list[str]) -> dict:
    total = 0
    truncated: list[str] = []
    for keyword in keywords:
        if total >= MAX_TOTAL_SEARCH_HITS:
            truncated.append(keyword)
            break
        try:
            payload = await ctx.tools.search_code(keyword, max_hits=200)
        except SandboxUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            await add_log(
                ctx.project_id,
                "warn",
                f"关键字搜索「{keyword}」失败：{exc}",
                stage_id=ctx.stage_id,
                worker_task_id=ctx.worker_task_id,
            )
            continue

        hits = payload.get("hits") or []
        if payload.get("truncated"):
            truncated.append(keyword)
        accepted = hits[: max(0, MAX_TOTAL_SEARCH_HITS - total)]
        total += len(accepted)
        examples = "；".join(
            f"{item.get('file_path')}:{item.get('line_no')}"
            for item in accepted[:5]
        )
        await add_log(
            ctx.project_id,
            "info",
            f"关键字搜索「{keyword}」命中 {len(hits)} 条"
            + (f"，示例：{examples}" if examples else ""),
            stage_id=ctx.stage_id,
            worker_task_id=ctx.worker_task_id,
        )

    if total >= MAX_TOTAL_SEARCH_HITS or truncated:
        await add_log(
            ctx.project_id,
            "warn",
            f"关键字搜索结果达到上限（总命中 {total} 条，单关键字上限 200 条），已截断"
            + (f"：{', '.join(truncated[:5])}" if truncated else ""),
            stage_id=ctx.stage_id,
            worker_task_id=ctx.worker_task_id,
        )
    return {
        "keywords": len(keywords),
        "hits": total,
        "truncated": bool(truncated or total >= MAX_TOTAL_SEARCH_HITS),
    }


async def _verification_summary(ctx: WorkerContext) -> dict:
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(Vulnerability.verify_status, func.count(Vulnerability.id))
                .where(
                    Vulnerability.project_id == ctx.project_id,
                    Vulnerability.run_no == ctx.run_no,
                )
                .group_by(Vulnerability.verify_status)
            )
        ).all()
    counts = {status: int(count) for status, count in rows}
    await add_chat(
        ctx.project_id,
        "code_analyst",
        "conclusion",
        f"复核漏洞验证结果：已验证 {counts.get('verified', 0)} 个，"
        f"失败 {counts.get('failed', 0)} 个，跳过 {counts.get('skipped', 0)} 个。",
    )
    return {"verify_status_counts": counts}


async def _read_files(
    ctx: WorkerContext, entries: list[dict]
) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    for entry in entries[:MAX_READ_FILES]:
        path = entry.get("path")
        if not path:
            continue
        try:
            payload = await ctx.tools.read_file(path)
        except SandboxUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            await add_log(
                ctx.project_id,
                "warn",
                f"读取文件失败，跳过：{path}（{exc}）",
                stage_id=ctx.stage_id,
                worker_task_id=ctx.worker_task_id,
            )
            continue
        if payload.get("binary") or payload.get("content") is None:
            continue
        files.append((path, payload["content"]))
    if entries and not files:
        raise WorkerError("源码文件读取全部失败，沙箱可能不可用，终止本轮分析")
    return files


async def _rule_engine_fallback(
    ctx: WorkerContext, entries: list[dict]
) -> tuple[list, list[tuple[str, str]]]:
    files = await _read_files(ctx, entries)
    return scan_files(files), files


async def run_code_analyst(ctx: WorkerContext) -> dict:
    if ctx.stage_name == "vulnerability_verify":
        return await _verification_summary(ctx)

    max_files = int(ctx.config.get("exec.max_files", 5000))
    await add_log(
        ctx.project_id,
        "info",
        "开始遍历源码并进行安全分析",
        stage_id=ctx.stage_id,
        worker_task_id=ctx.worker_task_id,
    )
    try:
        listing = await ctx.tools.list_files(max_files)
    except Exception as exc:  # noqa: BLE001
        raise WorkerError(f"遍历源码失败：{exc}") from exc

    entries = listing.get("files", [])
    if listing.get("truncated"):
        await add_log(
            ctx.project_id,
            "warn",
            f"源码文件数超过遍历上限 {max_files}，本轮只分析前 {len(entries)} 个文件",
            stage_id=ctx.stage_id,
            worker_task_id=ctx.worker_task_id,
        )
    if len(entries) > MAX_READ_FILES:
        await add_log(
            ctx.project_id,
            "warn",
            f"源码文件数 {len(entries)} 超过单轮读取上限 {MAX_READ_FILES}，"
            f"仅分析前 {MAX_READ_FILES} 个文件",
            stage_id=ctx.stage_id,
            worker_task_id=ctx.worker_task_id,
        )

    # FR-EXEC-03：任务词项 + 内置安全关键字搜索，结果写入日志
    keywords = build_search_keywords(ctx.task_content)
    search_summary = await _keyword_search(ctx, keywords)
    await add_chat(
        ctx.project_id,
        "code_analyst",
        "thought",
        f"关键字搜索完成：{search_summary['keywords']} 个关键字，"
        f"命中 {search_summary['hits']} 处"
        + ("（结果已截断）" if search_summary["truncated"] else "")
        + "，命中位置将作为分析重点。",
    )

    analysis_mode = "one_shot"
    if ctx.llm.active:
        configured = str(
            ctx.config.get("orchestration.analysis_mode", "one_shot")
        )
        analysis_mode = configured if configured in ("one_shot", "react") else "one_shot"

    files: list[tuple[str, str]] = []
    rule_findings: list = []
    if analysis_mode != "react":
        # one_shot / 规则引擎模式仍需先把源码读入内存
        files = await _read_files(ctx, entries)
        rule_findings = scan_files(files)

    findings = rule_findings
    mode = "mock"
    react_meta: dict | None = None
    if ctx.llm.active:
        if analysis_mode == "react":
            mode = "react"
            try:
                react = await run_react_analysis(ctx, entries)
                react_meta = {
                    "steps": react.steps,
                    "tool_calls": react.tool_calls,
                    "tokens": react.tokens,
                    "files_read": react.files_read,
                    "budget_exhausted": react.budget_exhausted,
                }
                if react.findings:
                    findings = react.findings
                    await add_log(
                        ctx.project_id,
                        "info",
                        f"ReAct 分析完成：{react.steps} 轮、{react.tool_calls} 次工具调用，"
                        f"读取 {react.files_read} 个文件，返回 {len(react.findings)} 个可校验候选",
                        stage_id=ctx.stage_id,
                        worker_task_id=ctx.worker_task_id,
                    )
                else:
                    findings, files = await _rule_engine_fallback(ctx, entries)
                    mode = "mock"
                    await add_log(
                        ctx.project_id,
                        "warn",
                        "ReAct 未返回可校验漏洞，本阶段使用规则引擎结果",
                        stage_id=ctx.stage_id,
                        worker_task_id=ctx.worker_task_id,
                    )
            except LLMUnavailable as exc:
                findings, files = await _rule_engine_fallback(ctx, entries)
                mode = "mock"
                await announce_fallback(ctx, str(exc))
            except LLMValidationError as exc:
                findings, files = await _rule_engine_fallback(ctx, entries)
                mode = "mock"
                await announce_llm_output_invalid(ctx, str(exc))
        else:
            mode = "llm"
            try:
                data = await ctx.llm.call_json(
                    code_analysis_messages(ctx.task_content, files)
                )
                llm_findings = parse_code_findings(data, files)
                if llm_findings:
                    findings = llm_findings
                    await add_log(
                        ctx.project_id,
                        "info",
                        f"LLM 分析完成：扫描 {len(files)} 个文件，"
                        f"返回 {len(llm_findings)} 个可校验候选漏洞（model={ctx.llm.model}）",
                        stage_id=ctx.stage_id,
                        worker_task_id=ctx.worker_task_id,
                    )
                else:
                    findings = rule_findings
                    mode = "mock"
                    await add_log(
                        ctx.project_id,
                        "warn",
                        "LLM 未返回可校验的漏洞，本阶段使用规则引擎结果",
                        stage_id=ctx.stage_id,
                        worker_task_id=ctx.worker_task_id,
                    )
            except LLMUnavailable as exc:
                findings = rule_findings
                mode = "mock"
                await announce_fallback(ctx, str(exc))
            except LLMValidationError as exc:
                findings = rule_findings
                mode = "mock"
                await announce_llm_output_invalid(ctx, str(exc))

    files_scanned = len(files)
    if not files and react_meta is not None:
        files_scanned = int(react_meta.get("files_read") or 0)

    await add_log(
        ctx.project_id,
        "info",
        f"安全分析完成（{mode}）：扫描 {files_scanned} 个文件，"
        f"发现 {len(findings)} 个候选漏洞",
        stage_id=ctx.stage_id,
        worker_task_id=ctx.worker_task_id,
    )

    saved = await save_findings(
        ctx.project_id,
        ctx.run_no,
        findings,
        stage_id=ctx.stage_id,
        worker_task_id=ctx.worker_task_id,
    )

    for finding in findings[:10]:
        await add_chat(
            ctx.project_id,
            "code_analyst",
            "evidence",
            f"在 {finding.file_path}:{finding.line_no} 发现{finding.vuln_title.split('：')[0]}："
            f"{finding.evidence_text[:200]}",
        )
    await add_chat(
        ctx.project_id,
        "code_analyst",
        "conclusion",
        f"代码分析完成（{mode} 模式）：新增漏洞 {saved['created_count']} 个，"
        f"更新 {saved['updated_count']} 个。",
    )

    summary = {
        "mode": mode,
        "files_scanned": files_scanned,
        "findings_found": len(findings),
        "created": saved["created_count"],
        "updated": saved["updated_count"],
        "vuln_codes": [item["vuln_code"] for item in saved["created"]],
        "keyword_search": search_summary,
        "llm_tokens": ctx.llm.token_count,
        "react": react_meta,
    }
    await add_log(
        ctx.project_id,
        "info",
        "漏洞检测结果：" + json.dumps(summary, ensure_ascii=False),
        stage_id=ctx.stage_id,
        worker_task_id=ctx.worker_task_id,
    )
    return summary
