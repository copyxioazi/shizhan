"""LLM 降级提示：运行内只提示一次，并写入日志与系统消息。"""

from __future__ import annotations

from app.core.logging import sanitize
from app.services.monitor_service import add_chat, add_log
from app.workers.base import WorkerContext


async def announce_fallback(ctx: WorkerContext, reason: str) -> None:
    if ctx.llm.fallback_announced:
        return
    ctx.llm.fallback_announced = True
    message = sanitize(str(reason))[:800]
    await add_log(
        ctx.project_id,
        "warn",
        f"LLM 调用失败，本轮剩余阶段切换规则引擎：{message}",
        stage_id=ctx.stage_id,
        worker_task_id=ctx.worker_task_id,
    )
    await add_chat(
        ctx.project_id,
        "system",
        "system",
        f"LLM 不可用，已切换为规则引擎模式。原因：{message}",
    )


async def announce_llm_output_invalid(
    ctx: WorkerContext, reason: str
) -> None:
    ctx.llm.disable(reason)
    await announce_fallback(ctx, reason)
