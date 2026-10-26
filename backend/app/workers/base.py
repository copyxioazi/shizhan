"""角色执行上下文与异常。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.orchestration.state import RunState
from app.sandbox.manager import SandboxRuntime
from app.services.llm_runtime import LLMRuntime
from app.tools.executor import ToolExecutor


class WorkerError(Exception):
    """角色失败（主角色失败将使阶段失败）。"""


@dataclass
class WorkerContext:
    project_id: int
    project_name: str
    task_content: str
    run_no: int
    stage_id: int
    stage_name: str
    worker_task_id: int
    sandbox: SandboxRuntime
    config: dict[str, Any]
    source_path: str
    llm: LLMRuntime
    # 运行状态视图与工具入口；worker 不再直接拼 sandbox helper 参数
    state: RunState
    tools: ToolExecutor
