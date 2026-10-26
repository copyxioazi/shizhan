"""配置与管理接口（仅管理员）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_admin
from app.core.errors import ApiError, ErrorCode, ok
from app.core.timeutil import cn_time, now_utc
from app.models import IsolationEnv, Project, RuntimeLog, User
from app.services import config_service
from app.services.monitor_service import add_log

router = APIRouter(prefix="/system", tags=["配置与管理"])


@router.get("/config")
async def get_config(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return ok(await config_service.get_config_map(db))


@router.put("/config")
async def update_config(
    payload: dict[str, Any] = Body(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return ok(await config_service.update_config(db, admin.id, payload))


@router.get("/users")
async def list_users(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """管理员筛选项目创建人时使用的只读用户列表。"""
    rows = (await db.execute(select(User).order_by(User.id))).scalars().all()
    return ok(
        [
            {"id": user.id, "username": user.username, "role": user.role}
            for user in rows
        ]
    )


@router.get("/logs")
async def system_logs(
    _: User = Depends(require_admin),
    project_id: int | None = Query(None),
    level: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    before_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(RuntimeLog)
    if project_id is not None:
        stmt = stmt.where(RuntimeLog.project_id == project_id)
    if level:
        stmt = stmt.where(RuntimeLog.log_level == level)
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
                "project_id": row.project_id,
                "stage_id": row.stage_id,
                "worker_task_id": row.worker_task_id,
                "log_level": row.log_level,
                "log_content": row.log_content,
                "created_at": cn_time(row.created_at),
            }
            for row in reversed(rows)
        ]
    )


@router.get("/isolation-envs")
async def list_isolation_envs(
    _: User = Depends(require_admin),
    env_status: str | None = Query(None),
    env_type: str | None = Query(None),
    project_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(IsolationEnv, Project.project_name).join(
        Project, Project.id == IsolationEnv.project_id
    )
    if env_status:
        stmt = stmt.where(IsolationEnv.env_status == env_status)
    if env_type:
        stmt = stmt.where(IsolationEnv.env_type == env_type)
    if project_id is not None:
        stmt = stmt.where(IsolationEnv.project_id == project_id)
    rows = (await db.execute(stmt.order_by(IsolationEnv.id))).all()
    return ok(
        [
            {
                "id": env.id,
                "project_id": env.project_id,
                "project_name": project_name,
                "env_type": env.env_type,
                "env_ref": env.env_ref,
                "env_status": env.env_status,
                "last_error": env.last_error,
                "updated_at": cn_time(env.updated_at),
            }
            for env, project_name in rows
        ]
    )


@router.post("/isolation-envs/{env_id}/cleanup")
async def cleanup_isolation_env(
    env_id: int,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    env = await db.get(IsolationEnv, env_id)
    if env is None:
        raise ApiError(404, ErrorCode.ENVIRONMENT_NOT_FOUND)
    if env.env_status == "running":
        raise ApiError(409, ErrorCode.ENVIRONMENT_STATE_CONFLICT, "运行中的环境不能清理")

    from app.sandbox.manager import SandboxManager
    from app.sandbox.source_sync import remove_remote_workspace

    manager = SandboxManager()
    try:
        if env.env_ref:
            await manager.stop(env.env_ref)
            await manager.remove(env.env_ref)
        await remove_remote_workspace(env.project_id)
    except Exception as exc:  # noqa: BLE001
        raise ApiError(500, ErrorCode.ENVIRONMENT_CREATE_FAILED, f"清理失败：{exc}") from exc
    finally:
        await manager.close()

    env.env_status = "destroyed"
    env.env_ref = None
    env.updated_at = now_utc()
    await db.commit()
    await add_log(
        None, "info", f"管理员清理隔离环境 env_id={env_id}（project_id={env.project_id}）"
    )
    return ok({"env_id": env_id, "env_status": "destroyed"})
