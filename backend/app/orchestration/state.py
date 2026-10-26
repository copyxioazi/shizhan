"""一轮运行的内存状态视图。

设计约束：

- 数据库仍是事实来源，``RunState`` 只承载调度过程中的上下文；
- 不在这里写库，也不复制数据库模型；
- 字段只保留编排、降级和后续图执行需要的通用信息。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunState:
    """单轮评估任务的运行状态。"""

    project_id: int
    run_no: int
    project_name: str
    task_content: str
    source_path: str

    stage_name: str = ""
    stage_id: int | None = None
    worker_task_id: int | None = None

    plan: dict[str, Any] = field(default_factory=dict)
    findings: list[Any] = field(default_factory=list)
    tool_trace: list[dict[str, Any]] = field(default_factory=list)

    token_count: int = 0
    fallback: bool = False
    error: str | None = None

    def enter_stage(self, stage_name: str, stage_id: int | None) -> None:
        self.stage_name = stage_name
        self.stage_id = stage_id
        self.worker_task_id = None

    def bind_worker(self, worker_task_id: int | None) -> None:
        self.worker_task_id = worker_task_id

    def record_plan(self, plan: dict[str, Any]) -> None:
        self.plan = dict(plan)

    def record_findings(self, findings: list[Any]) -> None:
        self.findings = [item for item in findings]

    def sync_tokens(self, token_count: int) -> None:
        self.token_count = int(token_count)

    def fail(self, message: str) -> None:
        self.error = message

    def snapshot(self) -> dict[str, Any]:
        """可写入日志/检查点的轻量快照，不含源码与凭据。"""
        return {
            "project_id": self.project_id,
            "run_no": self.run_no,
            "stage_name": self.stage_name,
            "stage_id": self.stage_id,
            "worker_task_id": self.worker_task_id,
            "plan_focus_areas": list(self.plan.get("focus_areas") or []),
            "findings": len(self.findings),
            "tool_calls": len(self.tool_trace),
            "token_count": self.token_count,
            "fallback": self.fallback,
            "error": self.error,
        }
