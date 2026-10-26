"""五类内置检测规则（SQL 注入、命令注入、路径穿越、IDOR、硬编码密钥）。

设计目标：
- 确定性：同一份源码、同一规则集，输出顺序与内容完全一致；
- 证据真实：文件路径、行号与片段均来自实际源码，不编造；
- 输出字段与 LLM 模式一致，由上层统一落库。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

RISK_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

EXCLUDE_PREFIXES = ("verify/", "tests/", "test/", "migrations/")

VERIFY_SCRIPTS = {
    "sql_injection": "python -B /src/verify/sql_injection.py",
    "command_injection": "python -B /src/verify/command_injection.py",
    "path_traversal": "python -B /src/verify/path_traversal.py",
    "idor": "python -B /src/verify/idor.py",
    "hardcoded_secret": None,
}

TITLES = {
    "sql_injection": "SQL 注入：查询语句拼接外部输入",
    "command_injection": "命令注入：外部输入进入命令执行",
    "path_traversal": "路径穿越：文件路径未规范化校验",
    "idor": "越权访问：按对象 ID 访问缺少归属校验",
    "hardcoded_secret": "硬编码密钥：敏感凭据以字面量存储",
}

IMPACT = {
    "sql_injection": "攻击者可读取、篡改或删除数据库内容，可能导致数据泄露与业务中断。",
    "command_injection": "攻击者可在沙箱内执行任意命令，读取源码与工作区数据，并可能横向影响评估环境。",
    "path_traversal": "攻击者可读取源码目录之外的文件，造成敏感信息泄露。",
    "idor": "攻击者可通过修改对象 ID 访问他人数据，造成越权读取或修改。",
    "hardcoded_secret": "凭据泄露后可用于冒用身份或访问关联系统，且无法通过轮换代码本身立即使其失效。",
}

CONDITION = {
    "sql_injection": "SQL 语句通过 f-string、format、% 或字符串拼接引入外部输入，未使用参数化查询。",
    "command_injection": "命令执行接口将外部输入直接拼接到 os.system / os.popen / subprocess 调用中。",
    "path_traversal": "文件路径由外部输入与基础目录拼接，未做规范化与根目录校验。",
    "idor": "按对象 ID 查询资源的处理函数未校验资源归属或当前用户权限。",
    "hardcoded_secret": "敏感凭据以字符串字面量形式写入源码。",
}

REPRODUCE = {
    "sql_injection": "1. 启动示例项目\n2. 向搜索接口提交包含引号与 OR 条件的参数\n3. 观察返回结果超出预期范围。",
    "command_injection": "1. 启动示例项目\n2. 向命令执行接口传入追加命令\n3. 观察接口返回追加命令的输出。",
    "path_traversal": "1. 启动示例项目\n2. 向文件下载接口传入 ../ 路径\n3. 观察读取到基础目录之外的文件。",
    "idor": "1. 以用户 A 身份访问用户 B 的对象 ID\n2. 观察接口直接返回他人数据。",
    "hardcoded_secret": "1. 读取源码中的凭据字面量\n2. 使用该凭据访问关联服务或构造签名。",
}

SQL_RE = re.compile(r"\b(select|insert|update|delete)\b", re.IGNORECASE)
SQL_INTERP_RE = re.compile(r"(f[\"'][^\n]*\{|\.format\s*\(|%\s*\(|\+\s*[A-Za-z_])")
REQUEST_RE = re.compile(
    r"(request\.|self\.path|parse_qs|urlparse|query_params|\bargs\[|\bform\[|\bparams\[)",
    re.IGNORECASE,
)
CMD_RE = re.compile(
    r"(os\.system\s*\(|os\.popen\s*\(|subprocess\.(?:run|Popen|call|check_output)\s*\([^)]*shell\s*=\s*True)",
    re.IGNORECASE,
)
PATH_JOIN_RE = re.compile(r"os\.path\.join\s*\([^)]*,[^)]*\)")
SEND_FILE_RE = re.compile(r"send_file\s*\(", re.IGNORECASE)
OPEN_RE = re.compile(r"open\s*\(([^)]*)\)", re.IGNORECASE)
PATH_GUARD_RE = re.compile(r"(realpath|secure_filename|normpath|commonpath)", re.IGNORECASE)
SECRET_ASSIGN_RE = re.compile(r"""^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(['"])([^'"]{8,})\2""")
ROUTE_RE = re.compile(
    r"^\s*@(?:(?:app|router)\.)?(?:route|get|post|put|delete)\((.*)\)\s*$"
)
DEF_RE = re.compile(r"^def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*:")
ID_PARAM_RE = re.compile(r"\b([a-z_]*id|[a-z_]*_no)\b", re.IGNORECASE)
OWNERSHIP_RE = re.compile(
    r"(owner|created_by|current_user|session\[|require_user|authorize|permission)",
    re.IGNORECASE,
)
IDOR_ROUTE_RE = re.compile(r"(order|profile|user|account|document|record)", re.IGNORECASE)


@dataclass
class Finding:
    category: str
    vuln_title: str
    risk_level: str
    file_path: str
    line_no: int
    impact_text: str
    condition_text: str
    evidence_text: str
    reproduce_steps_text: str
    verify_code_text: str | None

    def as_dict(self) -> dict:
        return {
            "category": self.category,
            "vuln_title": self.vuln_title,
            "risk_level": self.risk_level,
            "file_path": self.file_path,
            "line_no": self.line_no,
            "impact_text": self.impact_text,
            "condition_text": self.condition_text,
            "evidence_text": self.evidence_text,
            "reproduce_steps_text": self.reproduce_steps_text,
            "verify_code_text": self.verify_code_text,
        }


def _evidence_path(file_path: str, line_no: int, line: str) -> str:
    return f"{file_path}:{line_no}: {line.strip()[:300]}"


def _make_finding(category: str, file_path: str, line_no: int, line: str) -> Finding:
    return Finding(
        category=category,
        vuln_title=TITLES[category],
        risk_level={
            "sql_injection": "high",
            "command_injection": "critical",
            "path_traversal": "high",
            "idor": "medium",
            "hardcoded_secret": "medium",
        }[category],
        file_path=file_path,
        line_no=line_no,
        impact_text=IMPACT[category],
        condition_text=CONDITION[category],
        evidence_text=_evidence_path(file_path, line_no, line),
        reproduce_steps_text=REPRODUCE[category],
        verify_code_text=VERIFY_SCRIPTS[category],
    )


def _scan_sql(file_path: str, lines: list[str], has_request: bool) -> list[Finding]:
    if not has_request:
        return []
    for index, line in enumerate(lines, start=1):
        if SQL_RE.search(line) and SQL_INTERP_RE.search(line):
            return [_make_finding("sql_injection", file_path, index, line)]
    return []


def _scan_command(file_path: str, lines: list[str], has_request: bool) -> list[Finding]:
    if not has_request:
        return []
    for index, line in enumerate(lines, start=1):
        if CMD_RE.search(line):
            return [_make_finding("command_injection", file_path, index, line)]
    return []


def _scan_path(file_path: str, lines: list[str], has_request: bool, text: str) -> list[Finding]:
    if not has_request or PATH_GUARD_RE.search(text):
        return []
    for index, line in enumerate(lines, start=1):
        if PATH_JOIN_RE.search(line) or SEND_FILE_RE.search(line):
            return [_make_finding("path_traversal", file_path, index, line)]
        match = OPEN_RE.search(line)
        if match and re.search(r"\b(file|path|name|filename)\b", match.group(1), re.IGNORECASE):
            if not re.search(r"['\"][^'\"]*['\"]\s*,\s*['\"]", line):
                return [_make_finding("path_traversal", file_path, index, line)]
    return []


def _scan_idor(file_path: str, lines: list[str]) -> list[Finding]:
    for index, line in enumerate(lines):
        route_match = ROUTE_RE.match(line)
        if not route_match:
            continue
        route_text = route_match.group(1)
        if not IDOR_ROUTE_RE.search(route_text):
            continue
        body: list[str] = []
        def_index = None
        def_params = ""
        for offset in range(index + 1, min(index + 40, len(lines))):
            body_line = lines[offset]
            if ROUTE_RE.match(body_line):
                break
            def_match = DEF_RE.match(body_line)
            if def_match and def_index is None:
                def_index = offset
                def_params = def_match.group(2)
            if def_index is not None:
                body.append(body_line)
        if def_index is None:
            continue
        body_text = "\n".join(body)
        has_id = bool(ID_PARAM_RE.search(def_params)) or bool(
            re.search(r"\b\w*_?id\b", body_text, re.IGNORECASE)
        )
        if not has_id:
            continue
        if OWNERSHIP_RE.search(body_text):
            continue
        if not re.search(r"(orders?\[|select|fetch|find|get\()", body_text, re.IGNORECASE):
            continue
        return [
            _make_finding(
                "idor",
                file_path,
                def_index + 1,
                lines[def_index],
            )
        ]
    return []


def _scan_secret(file_path: str, lines: list[str]) -> list[Finding]:
    sensitive = re.compile(r"(secret|password|passwd|api_?key|token|access_?key)", re.IGNORECASE)
    for index, line in enumerate(lines, start=1):
        match = SECRET_ASSIGN_RE.match(line)
        if not match:
            continue
        name, _quote, value = match.groups()
        if not sensitive.search(name):
            continue
        lowered = value.lower()
        if lowered.startswith(("os.environ", "environ", "getenv", "none", "null")):
            continue
        if any(marker in lowered for marker in ("change-me", "changeme", "example", "placeholder", "${")):
            continue
        return [_make_finding("hardcoded_secret", file_path, index, line)]
    return []


def scan_file(file_path: str, content: str) -> list[Finding]:
    normalized = file_path.replace("\\", "/").lstrip("/")
    if normalized.startswith(EXCLUDE_PREFIXES):
        return []
    lines = content.splitlines()
    has_request = bool(REQUEST_RE.search(content))
    findings: list[Finding] = []
    findings.extend(_scan_sql(normalized, lines, has_request))
    findings.extend(_scan_command(normalized, lines, has_request))
    findings.extend(_scan_path(normalized, lines, has_request, content))
    findings.extend(_scan_idor(normalized, lines))
    findings.extend(_scan_secret(normalized, lines))
    return findings


def scan_files(files: list[tuple[str, str]]) -> list[Finding]:
    findings: list[Finding] = []
    for file_path, content in files:
        findings.extend(scan_file(file_path, content))
    findings.sort(
        key=lambda item: (
            RISK_ORDER.get(item.risk_level, 99),
            item.file_path,
            item.line_no,
            item.category,
        )
    )
    return findings
