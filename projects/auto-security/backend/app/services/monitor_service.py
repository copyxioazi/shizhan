"""监控数据落库：运行日志、聊天消息、资源采样。"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import get_logger, sanitize
from app.core.timeutil import cn_time, now_utc
from app.models import ChatMessage, ResourceUsage, RuntimeLog
from app.services.events import publish

logger = get_logger(__name__)

MESSAGE_MAX_LEN = 4000


def _append_log_file(project_id: int, line: str) -> None:
    try:
        directory = settings.runtime_logs_path / str(project_id)
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "runtime.log").open("a", encoding="utf-8") as handle:
            handle.write(sanitize(line) + "\n")
    except OSError as exc:
        # 文件写入失败不影响主流程，也不能再写项目日志（避免递归）
        logger.error("write runtime log file failed: %s", exc)


async def add_log(
    project_id: int | None,
    level: str,
    content: str,
    *,
    stage_id: int | None = None,
    worker_task_id: int | None = None,
) -> int | None:
    """写入 runtime_logs、日志文件并推送 runtime_log。"""
    content = sanitize(content)
    async with SessionLocal() as db:
        row = RuntimeLog(
            project_id=project_id,
            stage_id=stage_id,
            worker_task_id=worker_task_id,
            log_level=level,
            log_content=content,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        log_id = row.id
        created_at = row.created_at

    if project_id is not None:
        line = f"{cn_time(created_at)} [{level}] {content}"
        await asyncio.to_thread(_append_log_file, project_id, line)
        await publish(
            project_id,
            "runtime_log",
            {
                "log_id": log_id,
                "log_level": level,
                "log_content": content,
                "stage_id": stage_id,
                "worker_task_id": worker_task_id,
                "created_at": cn_time(created_at),
            },
        )
    else:
        logger.log(
            {"debug": 10, "info": 20, "warn": 30, "error": 40}.get(level, 20),
            "system: %s",
            content,
        )
    return log_id


async def add_chat(
    project_id: int,
    worker_role: str,
    message_type: str,
    message_text: str,
) -> int:
    text = sanitize(message_text)
    if len(text) > MESSAGE_MAX_LEN:
        text = text[:MESSAGE_MAX_LEN] + "...[truncated]"
    async with SessionLocal() as db:
        row = ChatMessage(
            project_id=project_id,
            worker_role=worker_role,
            message_type=message_type,
            message_text=text,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        message_id = row.id
        created_at = row.created_at

    await publish(
        project_id,
        "chat_message",
        {
            "message_id": message_id,
            "worker_role": worker_role,
            "message_type": message_type,
            "message_text": text,
            "created_at": cn_time(created_at),
        },
    )
    return message_id


async def add_resource(
    project_id: int, cpu_usage: float, memory_usage: float, token_count: int = 0
) -> dict[str, Any]:
    now = now_utc()
    async with SessionLocal() as db:
        row = ResourceUsage(
            project_id=project_id,
            cpu_usage=Decimal(str(round(cpu_usage, 2))),
            memory_usage=Decimal(str(round(memory_usage, 2))),
            token_count=token_count,
            recorded_at=now,
        )
        db.add(row)
        await db.commit()

    data = {
        "cpu_usage": round(cpu_usage, 2),
        "memory_usage": round(memory_usage, 2),
        "token_count": token_count,
        "recorded_at": cn_time(now),
    }
    await publish(project_id, "resource_usage", data)
    return data


def log_file_path(project_id: int) -> Path:
    return settings.runtime_logs_path / str(project_id) / "runtime.log"
