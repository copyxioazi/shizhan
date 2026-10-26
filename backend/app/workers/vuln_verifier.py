"""漏洞验证角色：在沙箱内执行验证脚本并更新验证状态。"""

from __future__ import annotations

import shlex
from typing import Any

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Vulnerability
from app.sandbox.manager import (
    SandboxCommandNotAllowed,
    SandboxCommandTimeout,
    SandboxQuotaExceeded,
    SandboxUnavailable,
)
from app.services.llm_runtime import LLMUnavailable
from app.services.monitor_service import add_chat, add_log
from app.workers.base import WorkerContext
from app.workers.llm_prompts import (
    LLMValidationError,
    parse_verification_plan,
    verification_messages,
    verification_retry_messages,
)
from app.workers.llm_support import announce_fallback, announce_llm_output_invalid

DESTRUCTIVE_MARKERS = (
    "/etc/",
    "/proc/",
    "/sys/",
    "/src/../",
    "rm -",
    "shutdown",
    "mkfs",
    "docker",
    "--privileged",
)


def _append_evidence(current: str, addition: str) -> str:
    merged = (current or "").rstrip() + "\n" + addition.strip()
    return merged[-6000:]


async def _load_verify_scripts(ctx: WorkerContext) -> list[str]:
    """读取 /src/verify 下的 Python 脚本清单。"""
    try:
        listing = await ctx.tools.list_files(
            int(ctx.config.get("exec.max_files", 5000))
        )
    except SandboxUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - 清单失败时仍可用既有命令
        await add_log(
            ctx.project_id,
            "warn",
            f"读取验证脚本清单失败：{exc}",
            stage_id=ctx.stage_id,
            worker_task_id=ctx.worker_task_id,
        )
        return []
    return sorted(
        f"/src/{item['path']}"
        for item in listing.get("files", [])
        if str(item.get("path", "")).startswith("verify/")
        and str(item.get("path", "")).endswith(".py")
    )


def _select_command(
    vuln: Vulnerability, decision: Any
) -> tuple[str, str]:
    existing_command = (vuln.verify_code_text or "").strip()
    command = existing_command
    decision_reason = ""
    if decision is not None:
        decision_reason = decision.reason
        if decision.action == "execute" and decision.verify_code_text:
            command = decision.verify_code_text
        elif decision.action == "skip" and not existing_command:
            command = ""
    return command, decision_reason


def _count_statuses(vulnerabilities: list[Vulnerability]) -> tuple[int, int, int]:
    verified = sum(1 for item in vulnerabilities if item.verify_status == "verified")
    failed = sum(1 for item in vulnerabilities if item.verify_status == "failed")
    skipped = sum(1 for item in vulnerabilities if item.verify_status == "skipped")
    return verified, failed, skipped


async def _verify_one(
    ctx: WorkerContext,
    vuln: Vulnerability,
    command: str,
    decision_reason: str = "",
) -> str:
    """执行单条验证命令并更新漏洞状态，返回 verified/failed/skipped。"""
    if not command:
        reason_text = f"（{decision_reason}）" if decision_reason else ""
        vuln.verify_status = "skipped"
        vuln.evidence_text = _append_evidence(
            vuln.evidence_text,
            f"无执行型验证手段，保留静态证据并以静态分析结论为准。{reason_text}",
        )
        await add_log(
            ctx.project_id,
            "info",
            f"{vuln.vuln_code} 无执行型验证脚本，标记 skipped",
            stage_id=ctx.stage_id,
            worker_task_id=ctx.worker_task_id,
        )
        await add_chat(
            ctx.project_id,
            "vuln_verifier",
            "conclusion",
            f"{vuln.vuln_code} 为静态证据型漏洞（{vuln.vuln_title}），标记为 skipped。",
        )
        return "skipped"

    # 记录最近一次实际命令，供失败重规划参考
    vuln.verify_code_text = command

    argv = shlex.split(command)
    if not argv:
        vuln.verify_status = "failed"
        vuln.evidence_text = _append_evidence(vuln.evidence_text, "验证命令为空。")
        return "failed"
    script = next(
        (argument for argument in argv if argument.startswith("/src/")),
        None,
    )
    if script is None:
        vuln.verify_status = "failed"
        vuln.evidence_text = _append_evidence(
            vuln.evidence_text, "验证脚本必须位于只读源码目录 /src 内。"
        )
        return "failed"

    # FR-VULN-03：执行前做语法检查，不生成 .pyc
    syntax_ok = True
    syntax_error = ""
    try:
        payload = await ctx.tools.syntax_check(script)
        syntax_ok = bool(payload.get("ok"))
        syntax_error = str(payload.get("error") or "")
    except SandboxUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        syntax_ok = False
        syntax_error = str(exc)
    if not syntax_ok:
        vuln.verify_status = "failed"
        vuln.evidence_text = _append_evidence(
            vuln.evidence_text,
            f"验证代码语法检查未通过：{syntax_error or '未知错误'}",
        )
        await add_log(
            ctx.project_id,
            "error",
            f"{vuln.vuln_code} 验证代码语法检查失败：{syntax_error}",
            stage_id=ctx.stage_id,
            worker_task_id=ctx.worker_task_id,
        )
        return "failed"

    lowered = command.lower()
    if any(marker in lowered for marker in DESTRUCTIVE_MARKERS):
        vuln.verify_status = "failed"
        vuln.evidence_text = _append_evidence(
            vuln.evidence_text, "验证命令包含破坏性操作，已拒绝执行。"
        )
        await add_log(
            ctx.project_id,
            "warn",
            f"{vuln.vuln_code} 验证命令被安全策略拒绝：{command}",
            stage_id=ctx.stage_id,
            worker_task_id=ctx.worker_task_id,
        )
        return "failed"

    try:
        result = await ctx.tools.run_command(argv)
        output = (result.get("stdout") or "") + (result.get("stderr") or "")
        confirmed = result.get("exit_code") == 0 and "VULN_CONFIRMED" in output
        vuln.verify_status = "verified" if confirmed else "failed"
        evidence_line = (
            f"验证命令：{command}\n"
            f"退出码：{result.get('exit_code')}\n"
            f"输出：{output.strip()[:1000]}"
        )
        vuln.evidence_text = _append_evidence(vuln.evidence_text, evidence_line)
        await add_log(
            ctx.project_id,
            "info",
            f"{vuln.vuln_code} 验证完成：{vuln.verify_status}（exit={result.get('exit_code')}）",
            stage_id=ctx.stage_id,
            worker_task_id=ctx.worker_task_id,
        )
        await add_chat(
            ctx.project_id,
            "vuln_verifier",
            "evidence",
            f"{vuln.vuln_code} 验证结果：{vuln.verify_status}，"
            f"退出码 {result.get('exit_code')}，输出 {output.strip()[:200]}",
        )
        return vuln.verify_status
    except SandboxCommandTimeout as exc:
        vuln.verify_status = "failed"
        vuln.evidence_text = _append_evidence(
            vuln.evidence_text, f"验证命令超时：{exc}"
        )
        await add_log(
            ctx.project_id,
            "warn",
            f"{vuln.vuln_code} 验证超时：{exc}",
            stage_id=ctx.stage_id,
            worker_task_id=ctx.worker_task_id,
        )
        return "failed"
    except SandboxCommandNotAllowed as exc:
        vuln.verify_status = "failed"
        vuln.evidence_text = _append_evidence(
            vuln.evidence_text, f"验证命令不在白名单：{exc}"
        )
        return "failed"
    except SandboxQuotaExceeded as exc:
        vuln.verify_status = "failed"
        vuln.evidence_text = _append_evidence(
            vuln.evidence_text, f"工作区配额超限，命令已终止：{exc}"
        )
        await add_log(
            ctx.project_id,
            "error",
            f"{vuln.vuln_code} 验证中止：{exc}",
            stage_id=ctx.stage_id,
            worker_task_id=ctx.worker_task_id,
        )
        return "failed"
    except SandboxUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        vuln.verify_status = "failed"
        vuln.evidence_text = _append_evidence(
            vuln.evidence_text, f"验证执行异常：{exc}"
        )
        await add_log(
            ctx.project_id,
            "error",
            f"{vuln.vuln_code} 验证异常：{exc}",
            stage_id=ctx.stage_id,
            worker_task_id=ctx.worker_task_id,
        )
        return "failed"


async def run_vuln_verifier(ctx: WorkerContext) -> dict:
    retry_round = 0
    async with SessionLocal() as db:
        vulnerabilities = (
            (
                await db.execute(
                    select(Vulnerability)
                    .where(
                        Vulnerability.project_id == ctx.project_id,
                        Vulnerability.run_no == ctx.run_no,
                        Vulnerability.verify_status == "pending",
                    )
                    .order_by(Vulnerability.vuln_code)
                )
            )
            .scalars()
            .all()
        )

        verify_scripts = await _load_verify_scripts(ctx)
        decisions: dict = {}
        if ctx.llm.active and vulnerabilities:
            payload = [
                {
                    "vuln_code": vuln.vuln_code,
                    "vuln_title": vuln.vuln_title,
                    "file_path": vuln.file_path,
                    "verify_code_text": vuln.verify_code_text,
                }
                for vuln in vulnerabilities
            ]
            try:
                data = await ctx.llm.call_json(
                    verification_messages(payload, verify_scripts)
                )
                decisions = parse_verification_plan(
                    data, {vuln.vuln_code for vuln in vulnerabilities}
                )
                await add_log(
                    ctx.project_id,
                    "info",
                    f"LLM 生成验证计划：{len(decisions)} 条（model={ctx.llm.model}）",
                    stage_id=ctx.stage_id,
                    worker_task_id=ctx.worker_task_id,
                )
            except LLMUnavailable as exc:
                await announce_fallback(ctx, str(exc))
            except LLMValidationError as exc:
                await announce_llm_output_invalid(ctx, str(exc))

        for vuln in vulnerabilities:
            command, decision_reason = _select_command(
                vuln, decisions.get(vuln.vuln_code)
            )
            await _verify_one(ctx, vuln, command, decision_reason)

        # 失败重规划：仅对 failed 漏洞再要一次策略，要求给出不同命令
        max_retries = int(
            ctx.config.get("orchestration.verify_max_retries", 0)
        )
        while retry_round < max_retries and ctx.llm.active:
            failed_vulns = [
                item
                for item in vulnerabilities
                if item.verify_status == "failed"
            ]
            if not failed_vulns:
                break
            retry_round += 1
            retry_payload = [
                {
                    "vuln_code": vuln.vuln_code,
                    "vuln_title": vuln.vuln_title,
                    "file_path": vuln.file_path,
                    "verify_code_text": vuln.verify_code_text,
                    "evidence_text": (vuln.evidence_text or "")[-800:],
                }
                for vuln in failed_vulns
            ]
            try:
                data = await ctx.llm.call_json(
                    verification_retry_messages(retry_payload, verify_scripts)
                )
                retry_decisions = parse_verification_plan(
                    data, {vuln.vuln_code for vuln in failed_vulns}
                )
            except LLMUnavailable as exc:
                await announce_fallback(ctx, str(exc))
                break
            except LLMValidationError as exc:
                await announce_llm_output_invalid(ctx, str(exc))
                break

            await add_log(
                ctx.project_id,
                "warn",
                f"验证失败重规划第 {retry_round} 轮：{len(retry_decisions)} 条",
                stage_id=ctx.stage_id,
                worker_task_id=ctx.worker_task_id,
            )
            for vuln in failed_vulns:
                decision = retry_decisions.get(vuln.vuln_code)
                if (
                    decision is None
                    or decision.action != "execute"
                    or not decision.verify_code_text
                ):
                    continue
                if decision.verify_code_text == (vuln.verify_code_text or "").strip():
                    await add_log(
                        ctx.project_id,
                        "warn",
                        f"{vuln.vuln_code} 重规划未给出新命令，保持 failed",
                        stage_id=ctx.stage_id,
                        worker_task_id=ctx.worker_task_id,
                    )
                    continue
                await _verify_one(
                    ctx, vuln, decision.verify_code_text, decision.reason
                )
            verified_now, failed_now, skipped_now = _count_statuses(
                vulnerabilities
            )
            await add_chat(
                ctx.project_id,
                "vuln_verifier",
                "conclusion",
                f"验证重规划第 {retry_round} 轮完成：已验证 {verified_now} 个，"
                f"失败 {failed_now} 个，跳过 {skipped_now} 个。",
            )

        verified, failed, skipped = _count_statuses(vulnerabilities)
        await db.commit()

    mode = "llm" if decisions else "mock"
    summary = {
        "mode": mode,
        "verified": verified,
        "failed": failed,
        "skipped": skipped,
        "total": len(vulnerabilities),
        "retry_rounds": retry_round,
        "llm_tokens": ctx.llm.token_count,
    }
    await add_chat(
        ctx.project_id,
        "vuln_verifier",
        "conclusion",
        f"漏洞验证完成（{mode} 模式）：已验证 {verified} 个，失败 {failed} 个，"
        f"跳过 {skipped} 个。",
    )
    await add_log(
        ctx.project_id,
        "info",
        f"漏洞验证汇总：{summary}",
        stage_id=ctx.stage_id,
        worker_task_id=ctx.worker_task_id,
    )
    return summary
