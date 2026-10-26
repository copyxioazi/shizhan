"""code_analyst 的 ReAct 工具循环（P0）。

模型通过 OpenAI tool calling 自行选择 ``list_files`` / ``read_file`` /
``search_code`` / ``syntax_check``；循环受轮次、token 预算和输出截断约束。
所有工具仍由 ``ToolRegistry`` 校验后进入沙箱执行。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.sandbox.manager import SandboxUnavailable
from app.services.llm_client import strip_code_fences
from app.services.llm_runtime import LLMUnavailable
from app.services.monitor_service import add_log
from app.tools.registry import ToolRegistry
from app.workers.base import WorkerContext
from app.workers.llm_prompts import (
    LLMValidationError,
    Finding,
    parse_code_findings,
)

MAX_TOOL_CALLS = 24
MAX_MANIFEST_ENTRIES = 200


@dataclass
class ReactAnalysisResult:
    findings: list[Finding] = field(default_factory=list)
    steps: int = 0
    tool_calls: int = 0
    files_read: int = 0
    tokens: int = 0
    truncated: bool = False
    budget_exhausted: bool = False


def react_messages(
    task_content: str,
    entries: list[dict[str, Any]],
    *,
    max_steps: int,
) -> list[dict[str, Any]]:
    """构造 ReAct 首轮消息：只给文件清单，不发源码正文。"""
    analysis_entries = [
        entry for entry in entries if not str(entry.get("path", "")).startswith("verify/")
    ]
    verify_scripts = [
        str(entry.get("path"))
        for entry in entries
        if str(entry.get("path", "")).startswith("verify/")
        and str(entry.get("path", "")).endswith(".py")
    ]

    manifest = "\n".join(
        f"- {entry.get('path')} ({entry.get('size', 0)} bytes)"
        for entry in analysis_entries[:MAX_MANIFEST_ENTRIES]
    )
    if len(analysis_entries) > MAX_MANIFEST_ENTRIES:
        manifest += f"\n- ... 其余 {len(analysis_entries) - MAX_MANIFEST_ENTRIES} 个文件省略"
    if not manifest:
        manifest = "（没有可分析的文本文件）"

    verify_hint = (
        "可用验证脚本（verify_code_text 只能引用其中之一）：\n"
        + "\n".join(f"- /src/{path}" for path in verify_scripts)
        if verify_scripts
        else "没有可用的 /src/verify 脚本；verify_code_text 请留空。"
    )

    user = (
        f"评估任务说明：\n{task_content}\n\n"
        f"源码文件清单：\n{manifest}\n\n"
        f"{verify_hint}\n\n"
        "你可以调用工具查看源码。建议先用 search_code 定位关键字，再按需 read_file；"
        f"不要盲目读取所有文件。最多进行 {max_steps} 轮工具调用。\n"
        "完成调查后，直接输出 JSON 数组，不要输出 Markdown 代码块或解释文字。\n"
        "每个漏洞对象字段：vuln_title, risk_level（critical/high/medium/low/info）, "
        "file_path, line_no, impact_text, condition_text, evidence_text, "
        "reproduce_steps_text, verify_code_text。\n"
        "evidence_text 必须包含源码中的真实行片段；line_no 必须是该片段在文件中的行号。"
    )
    return [
        {
            "role": "system",
            "content": (
                "你是 code_analyst（代码分析）。负责识别 SQL 注入、命令注入、"
                "路径穿越、越权访问与硬编码密钥等漏洞。只使用提供的工具，"
                "基于真实源码证据下结论。"
            ),
        },
        {"role": "user", "content": user},
    ]


async def run_react_analysis(
    ctx: WorkerContext, entries: list[dict[str, Any]]
) -> ReactAnalysisResult:
    """执行工具循环并返回可落地的漏洞候选。

    失败时抛出 ``LLMUnavailable`` / ``LLMValidationError``，由调用方回退。
    """
    client = ctx.llm.client
    if client is None:
        raise LLMUnavailable("LLM 客户端未初始化")

    max_steps = int(ctx.config.get("orchestration.react_max_steps", 5))
    max_tokens = int(ctx.config.get("orchestration.react_max_tokens", 8000))
    output_chars = int(
        ctx.config.get("orchestration.react_tool_output_chars", 6000)
    )
    registry = ToolRegistry(ctx.tools)
    messages = react_messages(ctx.task_content, entries, max_steps=max_steps)

    start_tokens = client.token_count
    result = ReactAnalysisResult()
    files_seen: dict[str, str] = {}
    force_final = False

    await add_log(
        ctx.project_id,
        "info",
        f"ReAct 模式启用：max_steps={max_steps}，token 预算={max_tokens}",
        stage_id=ctx.stage_id,
        worker_task_id=ctx.worker_task_id,
    )

    for step in range(max_steps):
        spent = client.token_count - start_tokens
        if spent >= max_tokens:
            result.budget_exhausted = True
            force_final = True
        try:
            if force_final:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "已达到工具调用预算，请基于已有证据立即输出 JSON 数组，"
                            "不要再调用工具。"
                        ),
                    }
                )
                response = await client.chat(messages)
            else:
                response = await client.chat(
                    messages, tools=registry.openai_tools()
                )
        except Exception as exc:  # noqa: BLE001 - 统一转为降级信号
            ctx.llm.disable(str(exc))
            raise LLMUnavailable(str(exc)) from exc

        result.steps = step + 1
        result.tokens = client.token_count - start_tokens

        if response.tool_calls and not force_final:
            messages.append(
                {
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": response.tool_calls,
                }
            )
            for call in response.tool_calls:
                if result.tool_calls >= MAX_TOOL_CALLS:
                    result.truncated = True
                    force_final = True
                    break
                result.tool_calls += 1
                name, arguments = _parse_tool_call(call)
                try:
                    payload = await registry.call(name, arguments)
                except SandboxUnavailable:
                    raise
                except Exception as exc:  # noqa: BLE001 - 工具错误回传给模型
                    payload = {"error": str(exc)[:300]}
                if name == "read_file" and isinstance(payload, dict):
                    path = _normalise_path(str(arguments.get("path", "")))
                    content = payload.get("content")
                    if path and isinstance(content, str):
                        files_seen[path] = content
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(call.get("id", "")),
                        "content": _truncate(
                            json.dumps(payload, ensure_ascii=False), output_chars
                        ),
                    }
                )
            if force_final:
                continue
            continue

        # 没有工具调用，视为最终答案
        return await _finalize(ctx, response.content, files_seen, result)

    # 轮次用尽：再要一次最终答案
    result.budget_exhausted = True
    messages.append(
        {
            "role": "user",
            "content": (
                "工具轮次已用尽，请基于已有证据立即输出 JSON 数组，不要调用工具。"
            ),
        }
    )
    try:
        response = await client.chat(messages)
    except Exception as exc:  # noqa: BLE001
        ctx.llm.disable(str(exc))
        raise LLMUnavailable(str(exc)) from exc
    result.tokens = client.token_count - start_tokens
    return await _finalize(ctx, response.content, files_seen, result)


async def _finalize(
    ctx: WorkerContext,
    content: str,
    files_seen: dict[str, str],
    result: ReactAnalysisResult,
) -> ReactAnalysisResult:
    text = strip_code_fences(content or "")
    if not text:
        raise LLMValidationError("ReAct 未返回最终 JSON")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMValidationError("ReAct 最终输出不是合法 JSON") from exc
    if not isinstance(data, list):
        raise LLMValidationError("ReAct 最终输出必须是 JSON 数组")

    # 模型可能引用了未读取过的文件；按需补读，保证证据落地校验有源码。
    for item in data[:30]:
        if not isinstance(item, dict):
            continue
        path = _normalise_path(str(item.get("file_path") or ""))
        if (
            not path
            or ".." in path.split("/")
            or path in files_seen
            or path.startswith("verify/")
        ):
            continue
        try:
            payload = await ctx.tools.read_file(path)
        except Exception:  # noqa: BLE001 - 读不到就交给 Schema 校验丢弃
            continue
        content_text = payload.get("content")
        if isinstance(content_text, str):
            files_seen[path] = content_text

    result.files_read = len(files_seen)
    result.findings = parse_code_findings(data, list(files_seen.items()))
    await add_log(
        ctx.project_id,
        "info",
        f"ReAct 完成：{result.steps} 轮，{result.tool_calls} 次工具调用，"
        f"{result.tokens} tokens，可落地候选 {len(result.findings)} 条"
        + ("（预算/轮次耗尽）" if result.budget_exhausted else ""),
        stage_id=ctx.stage_id,
        worker_task_id=ctx.worker_task_id,
    )
    return result


def _parse_tool_call(call: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    function = call.get("function") or {}
    name = str(function.get("name") or "")
    raw_arguments = function.get("arguments") or "{}"
    try:
        arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
    except json.JSONDecodeError:
        arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}
    return name, arguments


def _normalise_path(path: str) -> str:
    value = path.strip().replace("\\", "/")
    if value.startswith("/src/"):
        value = value[len("/src/") :]
    return value.removeprefix("./").lstrip("/")


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"
