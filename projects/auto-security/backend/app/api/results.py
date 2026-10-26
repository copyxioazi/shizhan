"""结果接口：漏洞、攻击路径、报告。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_visible_project
from app.core.errors import ok
from app.core.timeutil import cn_time
from app.models import Project
from app.services import result_service

router = APIRouter(prefix="/projects", tags=["结果"])


@router.get("/{project_id}/vulnerabilities")
async def list_vulnerabilities(
    project: Project = Depends(get_visible_project),
    run_no: int | None = Query(None),
    risk_level: str | None = Query(None),
    verify_status: str | None = Query(None),
    keyword: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return ok(
        await result_service.list_vulnerabilities(
            db,
            project.id,
            run_no=run_no,
            risk_level=risk_level,
            verify_status=verify_status,
            keyword=keyword,
        )
    )


@router.get("/{project_id}/vulnerabilities/{vuln_id}")
async def get_vulnerability(
    vuln_id: int,
    project: Project = Depends(get_visible_project),
    db: AsyncSession = Depends(get_db),
):
    return ok(await result_service.get_vulnerability(db, project.id, vuln_id))


@router.get("/{project_id}/attack-paths")
async def list_attack_paths(
    project: Project = Depends(get_visible_project),
    run_no: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return ok(await result_service.list_attack_paths(db, project.id, run_no))


@router.get("/{project_id}/attack-paths/{path_id}")
async def get_attack_path(
    path_id: int,
    project: Project = Depends(get_visible_project),
    db: AsyncSession = Depends(get_db),
):
    return ok(await result_service.get_attack_path(db, project.id, path_id))


@router.get("/{project_id}/report")
async def get_report(
    project: Project = Depends(get_visible_project),
    run_no: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    report, resolved_run = await result_service.get_report(db, project.id, run_no)
    return ok(
        {
            "report_id": report.id,
            "run_no": resolved_run,
            "report_markdown": report.report_markdown,
            "report_html": report.report_html,
            "report_file_path": report.report_file_path,
            "created_at": cn_time(report.created_at),
        }
    )


@router.get("/{project_id}/report/download")
async def download_report(
    project: Project = Depends(get_visible_project),
    run_no: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    report, resolved_run = await result_service.get_report(db, project.id, run_no)
    filename = f"report_{project.id}_{resolved_run}.html"
    return Response(
        content=report.report_html,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
