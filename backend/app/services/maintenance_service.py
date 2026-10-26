"""启动对账、孤儿容器清理与过程数据保留清理。"""

from __future__ import annotations

import shutil
from datetime import timedelta

from sqlalchemy import delete, select, update

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.core.timeutil import now_utc
from app.models import (
    ChatMessage,
    Project,
    ResourceUsage,
    RuntimeLog,
    RuntimeStage,
    WorkerTask,
)
from app.services.config_service import get_raw_config

logger = get_logger(__name__)


async def reconcile_on_startup() -> None:
    """把所有 running 状态收敛为 failed/cancelled，避免永久 running。"""
    now = now_utc()
    async with SessionLocal() as db:
        await db.execute(
            update(Project)
            .where(Project.project_status == "running")
            .values(project_status="failed", updated_at=now)
        )
        await db.execute(
            update(RuntimeStage)
            .where(RuntimeStage.stage_status == "running")
            .values(
                stage_status="failed",
                finished_at=now,
                error_message="server restarted",
            )
        )
        await db.execute(
            update(RuntimeStage)
            .where(RuntimeStage.stage_status == "pending")
            .values(stage_status="cancelled")
        )
        await db.execute(
            update(WorkerTask)
            .where(WorkerTask.task_status == "running")
            .values(
                task_status="failed",
                finished_at=now,
                error_message="server restarted",
            )
        )
        await db.commit()

    await cleanup_orphan_containers()
    logger.info("startup reconciliation completed")

    from app.services.monitor_service import add_log

    await add_log(None, "info", "后端启动对账完成：running 状态已收敛")


async def cleanup_orphan_containers() -> None:
    async with SessionLocal() as db:
        ids = set((await db.execute(select(Project.id))).scalars().all())
    try:
        from app.sandbox.manager import SandboxManager

        manager = SandboxManager()
        removed = await manager.cleanup_orphans(ids)
        if removed:
            from app.services.monitor_service import add_log

            await add_log(
                None, "info", f"已清理孤儿沙箱容器：{', '.join(removed)}"
            )
        await manager.close()
    except Exception as exc:  # noqa: BLE001 - Docker 不可用不阻断启动
        logger.warning("skip orphan container cleanup: %s", exc)


async def cleanup_retention() -> None:
    """删除超过保留天数的过程数据；保留项目、漏洞、路径、报告。"""
    config = await get_raw_config()
    days = int(config.get("runtime.retention_days", 30))
    threshold = now_utc() - timedelta(days=days)

    async with SessionLocal() as db:
        non_running = select(Project.id).where(Project.project_status != "running")
        project_ids = set(
            (
                await db.execute(
                    select(RuntimeLog.project_id)
                    .where(
                        RuntimeLog.created_at < threshold,
                        RuntimeLog.project_id.in_(non_running),
                        RuntimeLog.project_id.is_not(None),
                    )
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
        await db.execute(
            delete(RuntimeLog).where(
                RuntimeLog.created_at < threshold,
                RuntimeLog.project_id.in_(non_running),
            )
        )
        await db.execute(
            delete(ChatMessage).where(
                ChatMessage.created_at < threshold,
                ChatMessage.project_id.in_(non_running),
            )
        )
        await db.execute(
            delete(ResourceUsage).where(
                ResourceUsage.recorded_at < threshold,
                ResourceUsage.project_id.in_(non_running),
            )
        )
        await db.commit()

    for project_id in project_ids:
        directory = settings.runtime_logs_path / str(project_id)
        try:
            if directory.exists():
                shutil.rmtree(directory)
        except OSError as exc:
            logger.warning("remove old log dir failed: %s", exc)

    from app.services.monitor_service import add_log

    await add_log(
        None,
        "info",
        f"过程数据保留清理完成：阈值 {days} 天，涉及 {len(project_ids)} 个项目",
    )


async def retention_loop() -> None:
    import asyncio

    while True:
        try:
            await cleanup_retention()
        except Exception as exc:  # noqa: BLE001
            logger.warning("retention cleanup failed: %s", exc)
        await asyncio.sleep(24 * 3600)
