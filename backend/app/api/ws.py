"""WebSocket 实时流：鉴权、快照、心跳。"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.errors import ApiError
from app.core.security import decode_access_token
from app.core.timeutil import cn_time, now_utc
from app.models import ChatMessage, Project, RuntimeLog, RuntimeStage, User, WorkerTask
from app.services.events import envelope
from app.services.project_service import latest_run_no
from app.ws.manager import manager

router = APIRouter()

CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404
CLOSE_INTERNAL = 4410


async def _build_snapshot(db, project: Project) -> list[dict[str, Any]]:
    run_no = await latest_run_no(db, project.id)
    messages: list[dict[str, Any]] = []

    messages.append(
        envelope(
            project.id,
            "project_status",
            {
                "project_id": project.id,
                "project_status": project.project_status,
                "run_no": run_no or 0,
                "updated_at": cn_time(project.updated_at),
            },
        )
    )
    if run_no is not None:
        stages = (
            (
                await db.execute(
                    select(RuntimeStage)
                    .where(
                        RuntimeStage.project_id == project.id,
                        RuntimeStage.run_no == run_no,
                    )
                    .order_by(RuntimeStage.id)
                )
            )
            .scalars()
            .all()
        )
        for stage in stages:
            messages.append(
                envelope(
                    project.id,
                    "stage_status",
                    {
                        "project_id": project.id,
                        "stage_id": stage.id,
                        "stage_name": stage.stage_name,
                        "stage_status": stage.stage_status,
                        "run_no": stage.run_no,
                    },
                )
            )
        workers = (
            (
                await db.execute(
                    select(WorkerTask)
                    .join(RuntimeStage, RuntimeStage.id == WorkerTask.stage_id)
                    .where(
                        RuntimeStage.project_id == project.id,
                        RuntimeStage.run_no == run_no,
                    )
                    .order_by(WorkerTask.id)
                )
            )
            .scalars()
            .all()
        )
        for worker in workers:
            messages.append(
                envelope(
                    project.id,
                    "worker_status",
                    {
                        "worker_task_id": worker.id,
                        "worker_role": worker.worker_role,
                        "task_status": worker.task_status,
                        "stage_id": worker.stage_id,
                        "project_id": project.id,
                    },
                )
            )

    logs = (
        (
            await db.execute(
                select(RuntimeLog)
                .where(RuntimeLog.project_id == project.id)
                .order_by(RuntimeLog.id.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    for row in reversed(logs):
        messages.append(
            envelope(
                project.id,
                "runtime_log",
                {
                    "log_id": row.id,
                    "log_level": row.log_level,
                    "log_content": row.log_content,
                    "stage_id": row.stage_id,
                    "worker_task_id": row.worker_task_id,
                    "created_at": cn_time(row.created_at),
                },
            )
        )

    chats = (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.project_id == project.id)
                .order_by(ChatMessage.id.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    for row in reversed(chats):
        messages.append(
            envelope(
                project.id,
                "chat_message",
                {
                    "message_id": row.id,
                    "worker_role": row.worker_role,
                    "message_type": row.message_type,
                    "message_text": row.message_text,
                    "created_at": cn_time(row.created_at),
                },
            )
        )
    return messages


@router.websocket("/projects/{project_id}/stream")
async def project_stream(websocket: WebSocket, project_id: int) -> None:
    await websocket.accept()
    token = websocket.query_params.get("token")
    connection = None
    try:
        if not token:
            await websocket.close(code=CLOSE_UNAUTHORIZED)
            return
        try:
            payload = decode_access_token(token)
        except ApiError:
            await websocket.close(code=CLOSE_UNAUTHORIZED)
            return

        async with SessionLocal() as db:
            user = await db.get(User, payload["user_id"])
            if user is None or user.status != "active":
                await websocket.close(code=CLOSE_UNAUTHORIZED)
                return
            project = await db.get(Project, project_id)
            if project is None:
                await websocket.close(code=CLOSE_NOT_FOUND)
                return
            if user.role != "admin" and project.created_by != user.id:
                await websocket.close(code=CLOSE_FORBIDDEN)
                return
            snapshot = await _build_snapshot(db, project)
            connection = manager.connect(websocket, project_id, snapshot)

        while True:
            try:
                incoming = await asyncio.wait_for(websocket.receive_json(), timeout=90)
            except asyncio.TimeoutError:
                with contextlib.suppress(Exception):
                    await websocket.close(code=CLOSE_INTERNAL)
                break
            if isinstance(incoming, dict) and incoming.get("type") == "ping":
                connection.enqueue(
                    {"type": "pong", "timestamp": cn_time(now_utc())}
                )
    except WebSocketDisconnect:
        pass
    except Exception:
        with contextlib.suppress(Exception):
            await websocket.close(code=CLOSE_INTERNAL)
    finally:
        if connection is not None:
            await manager.disconnect(connection)
