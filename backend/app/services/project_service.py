"""项目生命周期服务：创建、查询、启动、停止、删除。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import ROOT_DIR, settings
from app.core.errors import ApiError, ErrorCode
from app.core.logging import get_logger
from app.core.timeutil import cn_time, now_utc
from app.models import (
    AttackPath,
    IsolationEnv,
    Project,
    Report,
    RuntimeStage,
    User,
    Vulnerability,
    WorkerTask,
)
from app.schemas.project import ProjectCreate
from app.services import config_service
from app.services.events import publish

logger = get_logger(__name__)

STAGE_NAMES = [
    "environment_scan",
    "code_analysis",
    "vulnerability_verify",
    "report_generate",
]
STARTABLE_STATUSES = {"created", "stopped", "failed"}


def _forbidden_source_dirs() -> list[Path]:
    return [
        settings.runtime_logs_path.resolve(),
        settings.reports_path.resolve(),
        settings.workspace_path.resolve(),
    ]


def validate_source_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        raise ApiError(422, ErrorCode.SOURCE_PATH_INVALID, "源码路径必须是绝对路径")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise ApiError(422, ErrorCode.SOURCE_PATH_INVALID, "源码路径不存在") from None
    if not resolved.is_dir():
        raise ApiError(422, ErrorCode.SOURCE_PATH_INVALID, "源码路径必须是目录")
    if not os.access(resolved, os.R_OK):
        raise ApiError(422, ErrorCode.SOURCE_PATH_INVALID, "源码路径不可读")

    if resolved == ROOT_DIR.resolve():
        raise ApiError(422, ErrorCode.SOURCE_PATH_INVALID, "不允许把应用安装目录作为源码目录")
    for forbidden in _forbidden_source_dirs():
        if resolved == forbidden or forbidden in resolved.parents:
            raise ApiError(
                422,
                ErrorCode.SOURCE_PATH_INVALID,
                "不允许使用运行时日志、报告或工作区目录作为源码目录",
            )
    return resolved


async def latest_run_no(db: AsyncSession, project_id: int) -> int | None:
    value = await db.scalar(
        select(func.max(RuntimeStage.run_no)).where(RuntimeStage.project_id == project_id)
    )
    return int(value) if value is not None else None


def _isolation_summary(env: IsolationEnv | None) -> dict[str, Any] | None:
    if env is None:
        return None
    return {
        "env_id": env.id,
        "env_type": env.env_type,
        "env_status": env.env_status,
        "env_ref": env.env_ref,
    }


async def _report_status(
    db: AsyncSession, project: Project, run_no: int | None
) -> str:
    if run_no is not None:
        report = await db.scalar(
            select(Report.id).where(
                Report.project_id == project.id, Report.run_no == run_no
            )
        )
        if report is not None:
            return "ready"
    if project.project_status == "running" and run_no is not None:
        stage = await db.scalar(
            select(RuntimeStage).where(
                RuntimeStage.project_id == project.id,
                RuntimeStage.run_no == run_no,
                RuntimeStage.stage_name == "report_generate",
            )
        )
        if stage is not None and stage.stage_status in ("pending", "running"):
            return "generating"
    if project.project_status == "failed":
        return "failed"
    return "none"


async def create_project(
    db: AsyncSession, user: User, payload: ProjectCreate
) -> dict[str, Any]:
    if payload.source_type != "local_path":
        raise ApiError(422, ErrorCode.SOURCE_TYPE_NOT_SUPPORTED)

    # FR-CONF-05：未显式指定时使用系统默认隔离类型
    cfg = await config_service.get_config_map(db)
    env_type = payload.isolation_type or str(
        cfg.get("isolation.default_type", "docker")
    )
    if env_type != "docker":
        raise ApiError(
            422,
            ErrorCode.SOURCE_TYPE_NOT_SUPPORTED,
            f"本期仅支持 Docker 隔离（当前默认类型：{env_type}）",
        )

    resolved = validate_source_path(payload.source_path)
    now = now_utc()
    project = Project(
        project_name=payload.project_name,
        source_type="local_path",
        source_path=str(resolved),
        task_content=payload.task_content,
        project_status="created",
        created_by=user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(project)
    await db.flush()
    env = IsolationEnv(
        project_id=project.id,
        env_type=env_type,
        env_ref=None,
        env_status="pending",
        created_at=now,
        updated_at=now,
    )
    db.add(env)
    await db.commit()
    await db.refresh(project)
    await db.refresh(env)

    return {
        "id": project.id,
        "project_name": project.project_name,
        "source_type": project.source_type,
        "source_path": project.source_path,
        "task_content": project.task_content,
        "project_status": project.project_status,
        "created_by": project.created_by,
        "isolation": {"env_type": env.env_type, "env_status": env.env_status},
        "created_at": cn_time(project.created_at),
        "updated_at": cn_time(project.updated_at),
    }


async def list_projects(
    db: AsyncSession,
    user: User,
    *,
    status: str | None = None,
    keyword: str | None = None,
    created_by: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    aggregate = (
        select(
            RuntimeStage.project_id.label("project_id"),
            func.max(RuntimeStage.started_at).label("last_started_at"),
            func.max(RuntimeStage.finished_at).label("last_finished_at"),
        )
        .group_by(RuntimeStage.project_id)
        .subquery()
    )
    stmt = (
        select(
            Project,
            User.username,
            aggregate.c.last_started_at,
            aggregate.c.last_finished_at,
        )
        .join(User, User.id == Project.created_by)
        .outerjoin(aggregate, aggregate.c.project_id == Project.id)
    )
    if user.role != "admin":
        stmt = stmt.where(Project.created_by == user.id)
    elif created_by is not None:
        stmt = stmt.where(Project.created_by == created_by)
    if status:
        stmt = stmt.where(Project.project_status == status)
    if keyword:
        stmt = stmt.where(Project.project_name.ilike(f"%{keyword}%"))
    stmt = stmt.order_by(Project.created_at.desc()).limit(limit).offset(offset)

    rows = (await db.execute(stmt)).all()
    return [
        {
            "id": project.id,
            "project_name": project.project_name,
            "source_type": project.source_type,
            "source_path": project.source_path,
            "task_content": project.task_content,
            "project_status": project.project_status,
            "created_by": project.created_by,
            "created_by_username": username,
            "created_at": cn_time(project.created_at),
            "last_started_at": cn_time(last_started),
            "last_finished_at": cn_time(last_finished),
        }
        for project, username, last_started, last_finished in rows
    ]


async def project_detail(
    db: AsyncSession, project: Project
) -> dict[str, Any]:
    run_no = await latest_run_no(db, project.id)
    env = await db.scalar(select(IsolationEnv).where(IsolationEnv.project_id == project.id))
    username = await db.scalar(select(User.username).where(User.id == project.created_by))

    vulnerability_count = 0
    verified_count = 0
    path_count = 0
    if run_no is not None:
        vulnerability_count = int(
            await db.scalar(
                select(func.count(Vulnerability.id)).where(
                    Vulnerability.project_id == project.id,
                    Vulnerability.run_no == run_no,
                )
            )
            or 0
        )
        verified_count = int(
            await db.scalar(
                select(func.count(Vulnerability.id)).where(
                    Vulnerability.project_id == project.id,
                    Vulnerability.run_no == run_no,
                    Vulnerability.verify_status == "verified",
                )
            )
            or 0
        )
        path_count = int(
            await db.scalar(
                select(func.count(AttackPath.id)).where(
                    AttackPath.project_id == project.id,
                    AttackPath.run_no == run_no,
                )
            )
            or 0
        )

    return {
        "id": project.id,
        "project_name": project.project_name,
        "source_type": project.source_type,
        "source_path": project.source_path,
        "task_content": project.task_content,
        "project_status": project.project_status,
        "created_by": project.created_by,
        "created_by_username": username,
        "created_at": cn_time(project.created_at),
        "updated_at": cn_time(project.updated_at),
        "current_run_no": run_no,
        "isolation": _isolation_summary(env),
        "counts": {
            "vulnerability_count": vulnerability_count,
            "verified_vulnerability_count": verified_count,
            "attack_path_count": path_count,
        },
        "report_status": await _report_status(db, project, run_no),
    }


async def start_project(db: AsyncSession, project_id: int) -> dict[str, Any]:
    project = await db.scalar(
        select(Project).where(Project.id == project_id).with_for_update()
    )
    if project is None:
        raise ApiError(404, ErrorCode.PROJECT_NOT_FOUND)
    if project.project_status not in STARTABLE_STATUSES:
        raise ApiError(409, ErrorCode.PROJECT_STATE_CONFLICT)

    cfg = await config_service.get_config_map(db)
    concurrency_limit = int(cfg["runtime.max_concurrent_projects"])
    running_count = int(
        await db.scalar(
            select(func.count(Project.id)).where(Project.project_status == "running")
        )
        or 0
    )
    if running_count >= concurrency_limit:
        raise ApiError(409, ErrorCode.PROJECT_CONCURRENCY_LIMIT)

    max_run = await db.scalar(
        select(func.max(RuntimeStage.run_no)).where(RuntimeStage.project_id == project_id)
    )
    run_no = int(max_run or 0) + 1
    started_at = now_utc()

    project.project_status = "running"
    project.updated_at = started_at
    for stage_name in STAGE_NAMES:
        db.add(
            RuntimeStage(
                project_id=project_id,
                run_no=run_no,
                stage_name=stage_name,
                stage_status="pending",
            )
        )

    env = await db.scalar(select(IsolationEnv).where(IsolationEnv.project_id == project_id))
    if env is not None:
        env.env_status = "pending"
        env.env_ref = None
        env.last_error = None
        env.updated_at = started_at
    await db.commit()

    await publish(
        project_id,
        "project_status",
        {
            "project_id": project_id,
            "project_status": "running",
            "run_no": run_no,
            "updated_at": cn_time(started_at),
        },
    )

    # 延迟导入，避免 scheduler -> services -> scheduler 循环
    from app.scheduler.manager import scheduler

    scheduler.start(project_id, run_no)
    return {
        "project_id": project_id,
        "run_no": run_no,
        "project_status": "running",
        "started_at": cn_time(started_at),
    }


async def stop_project(db: AsyncSession, project_id: int) -> dict[str, Any]:
    project = await db.scalar(
        select(Project).where(Project.id == project_id).with_for_update()
    )
    if project is None:
        raise ApiError(404, ErrorCode.PROJECT_NOT_FOUND)
    if project.project_status != "running":
        raise ApiError(409, ErrorCode.PROJECT_STATE_CONFLICT)

    from app.scheduler.manager import scheduler

    await scheduler.cancel(project_id)

    stopped_at = now_utc()
    project.project_status = "stopped"
    project.updated_at = stopped_at

    run_no = await latest_run_no(db, project_id)
    stage_stmt = select(RuntimeStage).where(RuntimeStage.project_id == project_id)
    if run_no is not None:
        stage_stmt = stage_stmt.where(RuntimeStage.run_no == run_no)
    stages = (
        (
            await db.execute(stage_stmt)
        )
        .scalars()
        .all()
    )
    for stage in stages:
        if stage.stage_status == "running":
            stage.stage_status = "cancelled"
            stage.finished_at = stopped_at
        elif stage.stage_status == "pending":
            stage.stage_status = "cancelled"

    await db.execute(
        update(WorkerTask)
        .where(WorkerTask.project_id == project_id, WorkerTask.task_status == "running")
        .values(task_status="cancelled", finished_at=stopped_at)
    )
    env = await db.scalar(select(IsolationEnv).where(IsolationEnv.project_id == project_id))
    if env is not None:
        env.env_status = "stopped"
        env.updated_at = stopped_at
    await db.commit()

    for stage in stages:
        await publish(
            project_id,
            "stage_status",
            {
                "project_id": project_id,
                "stage_id": stage.id,
                "stage_name": stage.stage_name,
                "stage_status": stage.stage_status,
                "run_no": stage.run_no,
            },
        )
    await publish(
        project_id,
        "project_status",
        {
            "project_id": project_id,
            "project_status": "stopped",
            "run_no": run_no or 0,
            "updated_at": cn_time(stopped_at),
        },
    )
    return {
        "project_id": project_id,
        "project_status": "stopped",
        "stopped_at": cn_time(stopped_at),
    }


async def _cleanup_files(project_id: int) -> list[str]:
    warnings: list[str] = []
    for directory in (
        settings.runtime_logs_path / str(project_id),
        settings.reports_path / str(project_id),
    ):
        try:
            if directory.exists():
                shutil.rmtree(directory)
        except OSError as exc:
            warnings.append(f"删除目录失败：{directory}（{exc}）")
    return warnings


async def delete_project(db: AsyncSession, project_id: int) -> dict[str, Any]:
    project = await db.scalar(
        select(Project).where(Project.id == project_id).with_for_update()
    )
    if project is None:
        raise ApiError(404, ErrorCode.PROJECT_NOT_FOUND)
    if project.project_status == "running":
        raise ApiError(409, ErrorCode.PROJECT_RUNNING_CANNOT_DELETE)

    warnings: list[str] = []
    warnings.extend(await _cleanup_files(project_id))

    # 沙箱容器与 VM 工作区清理为 best-effort，失败只记警告
    sandbox_manager = None
    try:
        from app.sandbox.manager import SandboxManager

        sandbox_manager = SandboxManager()
        await sandbox_manager.remove_project_containers(project_id)
    except Exception as exc:  # noqa: BLE001 - 清理失败不阻断数据库删除
        warnings.append(f"清理沙箱容器失败：{exc}")
    finally:
        if sandbox_manager is not None:
            try:
                await sandbox_manager.close()
            except Exception:  # noqa: BLE001
                pass
    try:
        from app.sandbox.source_sync import remove_remote_workspace

        await remove_remote_workspace(project_id)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"清理 VM 工作区失败：{exc}")

    await db.delete(project)
    await db.commit()
    if warnings:
        from app.services.monitor_service import add_log

        await add_log(
            None, "warn", f"删除项目 {project_id} 时存在清理警告：{'；'.join(warnings)}"
        )
    return {"deleted": True, "warnings": warnings}


async def list_stages(
    db: AsyncSession, project_id: int, run_no: int | None = None
) -> list[dict[str, Any]]:
    if run_no is None:
        run_no = await latest_run_no(db, project_id)
    if run_no is None:
        return []
    rows = (
        (
            await db.execute(
                select(RuntimeStage)
                .where(
                    RuntimeStage.project_id == project_id,
                    RuntimeStage.run_no == run_no,
                )
                .order_by(RuntimeStage.id)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": stage.id,
            "run_no": stage.run_no,
            "stage_name": stage.stage_name,
            "stage_status": stage.stage_status,
            "started_at": cn_time(stage.started_at),
            "finished_at": cn_time(stage.finished_at),
            "error_message": stage.error_message,
        }
        for stage in rows
    ]


async def list_workers(
    db: AsyncSession,
    project_id: int,
    run_no: int | None = None,
    stage_id: int | None = None,
    stage_name: str | None = None,
) -> list[dict[str, Any]]:
    stmt = (
        select(WorkerTask, RuntimeStage.stage_name, RuntimeStage.run_no)
        .join(RuntimeStage, RuntimeStage.id == WorkerTask.stage_id)
        .where(WorkerTask.project_id == project_id)
    )
    if stage_id is not None:
        stmt = stmt.where(WorkerTask.stage_id == stage_id)
    if stage_name is not None:
        stmt = stmt.where(RuntimeStage.stage_name == stage_name)
    if run_no is not None:
        stmt = stmt.where(RuntimeStage.run_no == run_no)
    elif stage_id is None and stage_name is None:
        latest = await latest_run_no(db, project_id)
        if latest is None:
            return []
        stmt = stmt.where(RuntimeStage.run_no == latest)
    stmt = stmt.order_by(WorkerTask.id)
    rows = (await db.execute(stmt)).all()
    return [
        {
            "id": task.id,
            "stage_id": task.stage_id,
            "stage_name": name,
            "run_no": run,
            "worker_role": task.worker_role,
            "task_status": task.task_status,
            "task_content": task.task_content,
            "result_summary": task.result_summary,
            "error_message": task.error_message,
            "started_at": cn_time(task.started_at),
            "finished_at": cn_time(task.finished_at),
        }
        for task, name, run in rows
    ]
