"""运维辅助角色：资源采样、环境状态记录。"""

from __future__ import annotations

from app.services.monitor_service import add_chat, add_log, add_resource
from app.workers.base import WorkerContext


async def run_ops_assistant(ctx: WorkerContext) -> dict:
    stats = await ctx.tools.stats()
    await add_resource(ctx.project_id, stats["cpu_usage"], stats["memory_usage"], 0)
    await add_log(
        ctx.project_id,
        "info",
        f"运维采样：CPU {stats['cpu_usage']}%，内存 {stats['memory_usage']} MB",
        stage_id=ctx.stage_id,
        worker_task_id=ctx.worker_task_id,
    )
    await add_chat(
        ctx.project_id,
        "ops_assistant",
        "conclusion",
        f"沙箱资源正常：CPU {stats['cpu_usage']}%，内存 {stats['memory_usage']} MB。",
    )
    return {
        "cpu_usage": stats["cpu_usage"],
        "memory_usage": stats["memory_usage"],
        "sandbox_container": ctx.tools.container_name,
    }
