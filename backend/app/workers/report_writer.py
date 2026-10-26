"""报告整理角色：生成攻击路径与最终报告。"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.timeutil import cn_time
from app.models import AttackPath, AttackPathItem, Vulnerability
from app.services.events import publish
from app.services.llm_runtime import LLMUnavailable
from app.services.monitor_service import add_chat, add_log
from app.services.report_service import generate_report
from app.workers.base import WorkerContext, WorkerError
from app.workers.llm_prompts import (
    LLMValidationError,
    parse_report_output,
    report_messages,
)
from app.workers.llm_support import announce_fallback, announce_llm_output_invalid

RISK_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _next_path_code(existing: list[str]) -> str:
    maximum = 0
    for code in existing:
        match = re.fullmatch(r"PATH-(\d+)", code or "")
        if match:
            maximum = max(maximum, int(match.group(1)))
    return f"PATH-{maximum + 1:03d}"


def _deterministic_path_spec(vulnerabilities: list[Vulnerability]) -> dict[str, Any]:
    return {
        "path_title": "已验证漏洞组合攻击链",
        "path_summary": (
            "将本轮已验证的漏洞按风险优先级串联，展示从初始入口到最终影响的利用链。"
        ),
        "final_impact_text": (
            "可组合利用上述漏洞获取敏感数据或执行未授权操作，建议优先修复最高风险项。"
        ),
        "items": [
            {
                "vuln_code": vuln.vuln_code,
                "step_order": index,
                "step_text": (
                    f"利用 {vuln.vuln_code}（{vuln.file_path}）："
                    f"{vuln.condition_text[:200]}"
                ),
            }
            for index, vuln in enumerate(vulnerabilities, start=1)
        ],
    }


async def run_report_writer(ctx: WorkerContext) -> dict:
    async with SessionLocal() as db:
        vulnerabilities = (
            (
                await db.execute(
                    select(Vulnerability).where(
                        Vulnerability.project_id == ctx.project_id,
                        Vulnerability.run_no == ctx.run_no,
                        Vulnerability.verify_status == "verified",
                    )
                )
            )
            .scalars()
            .all()
        )
        vulnerabilities = sorted(
            vulnerabilities,
            key=lambda item: (RISK_ORDER.get(item.risk_level, 99), item.vuln_code),
        )

        existing_paths = (
            (
                await db.execute(
                    select(AttackPath).where(
                        AttackPath.project_id == ctx.project_id,
                        AttackPath.run_no == ctx.run_no,
                    )
                )
            )
            .scalars()
            .all()
        )

        path_specs: list[dict[str, Any]] = []
        remediation: list[str] = []
        mode = "mock"
        if vulnerabilities and ctx.llm.active:
            payload = [
                {
                    "vuln_code": vuln.vuln_code,
                    "vuln_title": vuln.vuln_title,
                    "risk_level": vuln.risk_level,
                    "file_path": vuln.file_path,
                    "condition_text": vuln.condition_text,
                }
                for vuln in vulnerabilities
            ]
            try:
                data = await ctx.llm.call_json(
                    report_messages(ctx.project_name, ctx.task_content, payload)
                )
                path_specs, remediation = parse_report_output(
                    data, {vuln.vuln_code for vuln in vulnerabilities}
                )
                if path_specs:
                    mode = "llm"
                    await add_log(
                        ctx.project_id,
                        "info",
                        f"LLM 生成攻击路径 {len(path_specs)} 条、修复建议 "
                        f"{len(remediation)} 条（model={ctx.llm.model}）",
                        stage_id=ctx.stage_id,
                        worker_task_id=ctx.worker_task_id,
                    )
                else:
                    await add_log(
                        ctx.project_id,
                        "warn",
                        "LLM 未返回有效攻击路径，使用模板生成",
                        stage_id=ctx.stage_id,
                        worker_task_id=ctx.worker_task_id,
                    )
            except LLMUnavailable as exc:
                await announce_fallback(ctx, str(exc))
            except LLMValidationError as exc:
                await announce_llm_output_invalid(ctx, str(exc))

        if vulnerabilities and not existing_paths and not path_specs:
            path_specs = [_deterministic_path_spec(vulnerabilities)]

        created_paths = 0
        if not existing_paths:
            vuln_by_code = {vuln.vuln_code: vuln for vuln in vulnerabilities}
            existing_codes = [path.path_code for path in existing_paths]
            for spec in path_specs:
                items = []
                for item in spec.get("items", []):
                    vuln = vuln_by_code.get(item.get("vuln_code"))
                    if vuln is None:
                        continue
                    items.append(
                        {
                            "vuln_id": vuln.id,
                            "step_order": len(items) + 1,
                            "step_text": str(item.get("step_text") or "").strip()
                            or f"利用 {vuln.vuln_code}（{vuln.file_path}）",
                        }
                    )
                if not items:
                    continue
                code = _next_path_code(existing_codes)
                existing_codes.append(code)
                path = AttackPath(
                    project_id=ctx.project_id,
                    run_no=ctx.run_no,
                    path_code=code,
                    path_title=str(spec.get("path_title") or "攻击路径")[:255],
                    path_summary=str(spec.get("path_summary") or ""),
                    final_impact_text=str(spec.get("final_impact_text") or ""),
                )
                db.add(path)
                await db.flush()
                for item in items:
                    db.add(
                        AttackPathItem(
                            path_id=path.id,
                            vuln_id=item["vuln_id"],
                            step_order=item["step_order"],
                            step_text=item["step_text"],
                        )
                    )
                created_paths += 1
        await db.commit()
        path_count = int(
            len(
                (
                    await db.execute(
                        select(AttackPath.id).where(
                            AttackPath.project_id == ctx.project_id,
                            AttackPath.run_no == ctx.run_no,
                        )
                    )
                ).all()
            )
        )

    if created_paths:
        await add_chat(
            ctx.project_id,
            "report_writer",
            "conclusion",
            f"已基于 {len(vulnerabilities)} 个已验证漏洞生成 {created_paths} 条攻击路径"
            f"（{mode} 模式）。",
        )

    try:
        report = await generate_report(
            ctx.project_id,
            ctx.run_no,
            ctx.tools.image,
            remediation=remediation or None,
        )
    except Exception as exc:  # noqa: BLE001
        raise WorkerError(f"报告生成失败：{exc}") from exc

    await publish(
        ctx.project_id,
        "report_ready",
        {
            "project_id": ctx.project_id,
            "report_id": report.id,
            "run_no": ctx.run_no,
            "report_file_path": report.report_file_path,
        },
    )
    await add_log(
        ctx.project_id,
        "info",
        f"报告已生成：{report.report_file_path}",
        stage_id=ctx.stage_id,
        worker_task_id=ctx.worker_task_id,
    )
    await add_chat(
        ctx.project_id,
        "report_writer",
        "conclusion",
        f"报告生成完成（report_id={report.id}），包含项目概述、执行过程、漏洞汇总、"
        f"攻击路径、风险结论与修复建议。",
    )
    return {
        "mode": mode,
        "verified_vulnerabilities": len(vulnerabilities),
        "attack_paths": path_count,
        "report_id": report.id,
        "report_file_path": report.report_file_path,
        "llm_tokens": ctx.llm.token_count,
        "generated_at": cn_time(report.created_at),
    }
