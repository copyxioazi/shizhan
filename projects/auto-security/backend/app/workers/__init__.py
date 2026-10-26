"""六类执行角色。"""

from __future__ import annotations

from typing import Any

from app.workers.base import WorkerContext, WorkerError
from app.workers.code_analyst import run_code_analyst
from app.workers.env_checker import run_env_checker
from app.workers.general import run_general
from app.workers.ops_assistant import run_ops_assistant
from app.workers.report_writer import run_report_writer
from app.workers.vuln_verifier import run_vuln_verifier

WORKERS = {
    "general": run_general,
    "env_checker": run_env_checker,
    "code_analyst": run_code_analyst,
    "vuln_verifier": run_vuln_verifier,
    "report_writer": run_report_writer,
    "ops_assistant": run_ops_assistant,
}


async def run_worker(role: str, ctx: WorkerContext) -> dict[str, Any]:
    worker = WORKERS.get(role)
    if worker is None:
        raise WorkerError(f"未知角色：{role}")
    return await worker(ctx)


__all__ = ["WorkerContext", "WorkerError", "run_worker"]
