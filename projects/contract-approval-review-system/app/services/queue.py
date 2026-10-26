"""进程内 asyncio 队列与 worker。"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.config import settings
from app.services.pipeline import run_pipeline_sync

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Job:
    task_id: int
    resume_stage: str = "download"
    retry_count: int = 0


class JobQueueManager:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[Job] = asyncio.Queue(maxsize=settings.queue_maxsize)
        self._workers: list[asyncio.Task] = []
        self._inflight: set[int] = set()
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        if self._workers:
            return
        self._loop = asyncio.get_running_loop()
        # Queue/Lock 会绑定到首次使用的事件循环；服务重启或测试中复用
        # 单例时必须在新的循环上重建，否则 worker 会静默失效。
        self.queue = asyncio.Queue(maxsize=settings.queue_maxsize)
        self._lock = asyncio.Lock()
        self._inflight = set()
        for index in range(settings.worker_concurrency):
            self._workers.append(
                asyncio.create_task(self._worker(index), name=f"review-worker-{index}")
            )

    async def stop(self) -> None:
        for task in self._workers:
            task.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def enqueue(self, job: Job) -> bool:
        """同一 task_id 在途时拒绝重复入队。"""
        async with self._lock:
            if job.task_id in self._inflight:
                return False
            self._inflight.add(job.task_id)
        await self.queue.put(job)
        return True

    def enqueue_sync(self, job: Job, timeout: float = 5.0) -> bool:
        """同步路由在工作线程中调用；把入队协程投递回事件循环。"""
        if self._loop is None or not self._loop.is_running():
            raise RuntimeError("队列尚未启动")
        future = asyncio.run_coroutine_threadsafe(self.enqueue(job), self._loop)
        return bool(future.result(timeout=timeout))

    def is_inflight(self, task_id: int) -> bool:
        return task_id in self._inflight

    def pending_count(self) -> int:
        return self.queue.qsize()

    async def _worker(self, index: int) -> None:
        while True:
            job = await self.queue.get()
            try:
                await asyncio.to_thread(run_pipeline_sync, job)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("pipeline failed for task %s", job.task_id)
            finally:
                self._inflight.discard(job.task_id)
                self.queue.task_done()


_manager: JobQueueManager | None = None


def get_queue_manager() -> JobQueueManager:
    global _manager
    if _manager is None:
        _manager = JobQueueManager()
    return _manager
