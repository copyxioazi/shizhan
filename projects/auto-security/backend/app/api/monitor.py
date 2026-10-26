"""监控接口：日志、资源、聊天消息。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_visible_project
from app.core.errors import ok
from app.core.timeutil import cn_time
from app.models import ChatMessage, Project, ResourceUsage, RuntimeLog

router = APIRouter(prefix="/projects", tags=["监控"])


@router.get("/{project_id}/logs")
async def list_logs(
    project: Project = Depends(get_visible_project),
    level: str | None = Query(None),
    stage_id: int | None = Query(None),
    worker_task_id: int | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    before_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(RuntimeLog).where(RuntimeLog.project_id == project.id)
    if level:
        stmt = stmt.where(RuntimeLog.log_level == level)
    if stage_id is not None:
        stmt = stmt.where(RuntimeLog.stage_id == stage_id)
    if worker_task_id is not None:
        stmt = stmt.where(RuntimeLog.worker_task_id == worker_task_id)
    if before_id is not None:
        stmt = stmt.where(RuntimeLog.id < before_id)
    rows = (
        (await db.execute(stmt.order_by(RuntimeLog.id.desc()).limit(limit)))
        .scalars()
        .all()
    )
    return ok(
        [
            {
                "id": row.id,
                "stage_id": row.stage_id,
                "worker_task_id": row.worker_task_id,
                "log_level": row.log_level,
                "log_content": row.log_content,
                "created_at": cn_time(row.created_at),
            }
            for row in reversed(rows)
        ]
    )


@router.get("/{project_id}/resources")
async def list_resources(
    project: Project = Depends(get_visible_project),
    limit: int = Query(300, ge=1, le=2000),
    since: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ResourceUsage).where(ResourceUsage.project_id == project.id)
    if since is not None:
        stmt = stmt.where(ResourceUsage.recorded_at >= since)
    rows = (
        (
            await db.execute(
                stmt.order_by(ResourceUsage.recorded_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return ok(
        [
            {
                "cpu_usage": float(row.cpu_usage),
                "memory_usage": float(row.memory_usage),
                "token_count": row.token_count,
                "recorded_at": cn_time(row.recorded_at),
            }
            for row in reversed(rows)
        ]
    )


@router.get("/{project_id}/messages")
async def list_messages(
    project: Project = Depends(get_visible_project),
    limit: int = Query(100, ge=1, le=500),
    before_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ChatMessage).where(ChatMessage.project_id == project.id)
    if before_id is not None:
        stmt = stmt.where(ChatMessage.id < before_id)
    rows = (
        (await db.execute(stmt.order_by(ChatMessage.id.desc()).limit(limit)))
        .scalars()
        .all()
    )
    return ok(
        [
            {
                "id": row.id,
                "worker_role": row.worker_role,
                "message_type": row.message_type,
                "message_text": row.message_text,
                "created_at": cn_time(row.created_at),
            }
            for row in reversed(rows)
        ]
    )
