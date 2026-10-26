"""单项目多连接广播。

每个连接拥有独立发送队列，慢客户端丢弃最旧消息，不阻塞调度器。
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket

from app.core.logging import get_logger

logger = get_logger(__name__)

QUEUE_MAXSIZE = 1000


class WSConnection:
    def __init__(self, websocket: WebSocket, project_id: int) -> None:
        self.websocket = websocket
        self.project_id = project_id
        self.queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(
            maxsize=QUEUE_MAXSIZE
        )
        self._sender: asyncio.Task[None] | None = None
        self.closed = False

    def start(self, initial_messages: list[dict[str, Any]] | None = None) -> None:
        for message in initial_messages or []:
            self.queue.put_nowait(message)
        self._sender = asyncio.create_task(self._send_loop())

    async def _send_loop(self) -> None:
        try:
            while True:
                message = await self.queue.get()
                if message is None:
                    break
                await self.websocket.send_json(message)
        except (asyncio.CancelledError, RuntimeError, Exception):
            # 连接已断开；由路由侧负责清理
            pass

    def enqueue(self, message: dict[str, Any]) -> None:
        if self.closed:
            return
        if self.queue.full():
            try:
                self.queue.get_nowait()
                logger.warning(
                    "ws slow client: dropped oldest message (project_id=%s)",
                    self.project_id,
                )
            except asyncio.QueueEmpty:
                pass
        self.queue.put_nowait(message)

    async def stop(self) -> None:
        self.closed = True
        if self._sender is not None:
            self._sender.cancel()
            try:
                await self._sender
            except (asyncio.CancelledError, Exception):
                pass


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, list[WSConnection]] = {}
        self._lock = asyncio.Lock()

    def connect(
        self,
        websocket: WebSocket,
        project_id: int,
        initial_messages: list[dict[str, Any]] | None = None,
    ) -> WSConnection:
        connection = WSConnection(websocket, project_id)
        self._connections.setdefault(project_id, []).append(connection)
        connection.start(initial_messages)
        return connection

    async def disconnect(self, connection: WSConnection) -> None:
        connections = self._connections.get(connection.project_id, [])
        if connection in connections:
            connections.remove(connection)
        if not connections:
            self._connections.pop(connection.project_id, None)
        await connection.stop()

    async def broadcast(self, project_id: int, message: dict[str, Any]) -> None:
        for connection in list(self._connections.get(project_id, [])):
            connection.enqueue(message)

    def connection_count(self, project_id: int) -> int:
        return len(self._connections.get(project_id, []))


manager = ConnectionManager()
