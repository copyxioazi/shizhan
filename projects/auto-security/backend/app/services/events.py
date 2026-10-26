"""统一实时消息包络与广播入口。"""

from __future__ import annotations

from typing import Any

from app.core.timeutil import cn_time, now_utc
from app.ws.manager import manager

MESSAGE_TYPES = {
    "project_status",
    "stage_status",
    "worker_status",
    "chat_message",
    "runtime_log",
    "resource_usage",
    "vulnerability_found",
    "report_ready",
}


def envelope(project_id: int, message_type: str, data: dict[str, Any]) -> dict[str, Any]:
    assert message_type in MESSAGE_TYPES, f"unknown ws message type: {message_type}"
    return {
        "type": message_type,
        "project_id": project_id,
        "timestamp": cn_time(now_utc()),
        "data": data,
    }


async def publish(project_id: int, message_type: str, data: dict[str, Any]) -> None:
    await manager.broadcast(project_id, envelope(project_id, message_type, data))
