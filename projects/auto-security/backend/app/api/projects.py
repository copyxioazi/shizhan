"""项目接口：创建、列表、详情、启动、停止、删除、阶段与角色。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user, get_visible_project
from app.core.errors import ApiError, ErrorCode, ok
from app.models import Project, User
from app.schemas.project import ProjectCreate
from app.services import project_service

router = APIRouter(prefix="/projects", tags=["项目"])


@router.post("", status_code=201)
async def create_project(
    payload: ProjectCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await project_service.create_project(db, user, payload))


@router.get("")
async def list_projects(
    status: str | None = Query(None),
    keyword: str | None = Query(None),
    created_by: int | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await project_service.list_projects(
        db,
        user,
        status=status,
        keyword=keyword,
        created_by=created_by,
        limit=limit,
        offset=offset,
    )
    return ok(data)


@router.get("/{project_id}")
async def project_detail(
    project: Project = Depends(get_visible_project),
    db: AsyncSession = Depends(get_db),
):
    return ok(await project_service.project_detail(db, project))


@router.post("/{project_id}/start")
async def start_project(
    project: Project = Depends(get_visible_project),
    db: AsyncSession = Depends(get_db),
):
    return ok(await project_service.start_project(db, project.id))


@router.post("/{project_id}/stop")
async def stop_project(
    project: Project = Depends(get_visible_project),
    db: AsyncSession = Depends(get_db),
):
    return ok(await project_service.stop_project(db, project.id))


@router.delete("/{project_id}")
async def delete_project(
    project: Project = Depends(get_visible_project),
    confirm: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    if not confirm:
        raise ApiError(400, ErrorCode.DELETE_CONFIRM_REQUIRED)
    return ok(await project_service.delete_project(db, project.id))


@router.get("/{project_id}/stages")
async def list_stages(
    project: Project = Depends(get_visible_project),
    run_no: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return ok(await project_service.list_stages(db, project.id, run_no))


@router.get("/{project_id}/workers")
async def list_workers(
    project: Project = Depends(get_visible_project),
    run_no: int | None = Query(None),
    stage_id: int | None = Query(None),
    stage_name: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return ok(
        await project_service.list_workers(
            db, project.id, run_no=run_no, stage_id=stage_id, stage_name=stage_name
        )
    )
