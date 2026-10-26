"""漏洞、攻击路径、报告的查询服务。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, ErrorCode
from app.core.timeutil import cn_time
from app.models import (
    AttackPath,
    AttackPathItem,
    Report,
    Vulnerability,
)
from app.services.project_service import latest_run_no

RISK_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
RANK_TO_RISK = {value: key for key, value in RISK_RANK.items()}


async def resolve_run_no(
    db: AsyncSession, project_id: int, run_no: int | None
) -> int | None:
    return run_no if run_no is not None else await latest_run_no(db, project_id)


async def list_vulnerabilities(
    db: AsyncSession,
    project_id: int,
    *,
    run_no: int | None = None,
    risk_level: str | None = None,
    verify_status: str | None = None,
    keyword: str | None = None,
) -> list[dict[str, Any]]:
    resolved = await resolve_run_no(db, project_id, run_no)
    if resolved is None:
        return []
    stmt = select(Vulnerability).where(
        Vulnerability.project_id == project_id, Vulnerability.run_no == resolved
    )
    if risk_level:
        stmt = stmt.where(Vulnerability.risk_level == risk_level)
    if verify_status:
        stmt = stmt.where(Vulnerability.verify_status == verify_status)
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(
            Vulnerability.vuln_title.ilike(pattern)
            | Vulnerability.file_path.ilike(pattern)
        )
    stmt = stmt.order_by(
        case(
            {level: rank for level, rank in RISK_RANK.items()},
            value=Vulnerability.risk_level,
            else_=99,
        ),
        Vulnerability.vuln_code.asc(),
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": row.id,
            "vuln_code": row.vuln_code,
            "vuln_title": row.vuln_title,
            "risk_level": row.risk_level,
            "file_path": row.file_path,
            "verify_status": row.verify_status,
            "created_at": cn_time(row.created_at),
        }
        for row in rows
    ]


async def get_vulnerability(
    db: AsyncSession, project_id: int, vuln_id: int
) -> dict[str, Any]:
    row = await db.scalar(
        select(Vulnerability).where(
            Vulnerability.id == vuln_id, Vulnerability.project_id == project_id
        )
    )
    if row is None:
        raise ApiError(404, ErrorCode.VULNERABILITY_NOT_FOUND)
    return {
        "id": row.id,
        "vuln_code": row.vuln_code,
        "vuln_title": row.vuln_title,
        "risk_level": row.risk_level,
        "file_path": row.file_path,
        "verify_status": row.verify_status,
        "created_at": cn_time(row.created_at),
        "impact_text": row.impact_text,
        "condition_text": row.condition_text,
        "evidence_text": row.evidence_text,
        "reproduce_steps_text": row.reproduce_steps_text,
        "verify_code_text": row.verify_code_text,
    }


async def list_attack_paths(
    db: AsyncSession, project_id: int, run_no: int | None = None
) -> list[dict[str, Any]]:
    resolved = await resolve_run_no(db, project_id, run_no)
    if resolved is None:
        return []
    paths = (
        (
            await db.execute(
                select(AttackPath)
                .where(
                    AttackPath.project_id == project_id,
                    AttackPath.run_no == resolved,
                )
                .order_by(AttackPath.path_code)
            )
        )
        .scalars()
        .all()
    )
    result: list[dict[str, Any]] = []
    for path in paths:
        rows = (
            await db.execute(
                select(Vulnerability.risk_level)
                .join(AttackPathItem, AttackPathItem.vuln_id == Vulnerability.id)
                .where(AttackPathItem.path_id == path.id)
            )
        ).all()
        levels = [row[0] for row in rows]
        max_risk = min(levels, key=lambda level: RISK_RANK.get(level, 99)) if levels else None
        result.append(
            {
                "id": path.id,
                "path_code": path.path_code,
                "path_title": path.path_title,
                "path_summary": path.path_summary,
                "vuln_count": len(levels),
                "max_risk_level": max_risk,
                "final_impact_text": path.final_impact_text,
                "created_at": cn_time(path.created_at),
            }
        )
    return result


async def get_attack_path(
    db: AsyncSession, project_id: int, path_id: int
) -> dict[str, Any]:
    path = await db.scalar(
        select(AttackPath).where(
            AttackPath.id == path_id, AttackPath.project_id == project_id
        )
    )
    if path is None:
        raise ApiError(404, ErrorCode.ATTACK_PATH_NOT_FOUND)

    rows = (
        await db.execute(
            select(AttackPathItem, Vulnerability)
            .join(Vulnerability, Vulnerability.id == AttackPathItem.vuln_id)
            .where(AttackPathItem.path_id == path.id)
            .order_by(AttackPathItem.step_order)
        )
    ).all()
    items = [
        {
            "step_order": item.step_order,
            "step_text": item.step_text,
            "vuln_id": vuln.id,
            "vuln_code": vuln.vuln_code,
            "vuln_title": vuln.vuln_title,
            "risk_level": vuln.risk_level,
            "file_path": vuln.file_path,
            "verify_status": vuln.verify_status,
        }
        for item, vuln in rows
    ]
    return {
        "id": path.id,
        "path_code": path.path_code,
        "path_title": path.path_title,
        "path_summary": path.path_summary,
        "final_impact_text": path.final_impact_text,
        "run_no": path.run_no,
        "created_at": cn_time(path.created_at),
        "items": items,
    }


async def get_report(
    db: AsyncSession, project_id: int, run_no: int | None = None
) -> tuple[Report, int]:
    resolved = await resolve_run_no(db, project_id, run_no)
    if resolved is None:
        raise ApiError(404, ErrorCode.REPORT_NOT_READY)
    report = await db.scalar(
        select(Report).where(
            Report.project_id == project_id, Report.run_no == resolved
        )
    )
    if report is None:
        raise ApiError(404, ErrorCode.REPORT_NOT_READY)
    return report, resolved
