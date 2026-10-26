"""阶段编排接口与两种实现。

- ``FixedOrchestrator``：保持现有四阶段串行逻辑；
- ``LangGraphOrchestrator``：用 LangGraph StateGraph 表达同样的固定流程。

两种实现只依赖 ``StageHooks`` 回调，不直接接触数据库、沙箱或 worker。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol, TypedDict

try:  # LangGraph 是可选依赖；缺失时由调度器回退 fixed
    from langgraph.graph import END, START, StateGraph

    LANGGRAPH_AVAILABLE = True
except ImportError:  # pragma: no cover - 未安装时走回退分支
    END = "__end__"  # type: ignore[assignment]
    START = "__start__"  # type: ignore[assignment]
    StateGraph = None  # type: ignore[assignment]
    LANGGRAPH_AVAILABLE = False


class RunAborted(Exception):
    """失败已由 hooks 记录，编排器只需结束。"""


class StageAborted(Exception):
    """单个阶段失败；由调度器统一写入项目失败状态。"""

    def __init__(self, message: str, stage_id: int | None, stage_name: str) -> None:
        super().__init__(message)
        self.message = message
        self.stage_id = stage_id
        self.stage_name = stage_name


@dataclass(frozen=True)
class StageHooks:
    begin: Callable[[str], Awaitable[int]]
    execute: Callable[[str, int], Awaitable[None]]
    complete: Callable[[str, int], Awaitable[None]]
    after_environment_scan: Callable[[], Awaitable[None]]
    # 仅 LangGraph 引擎使用：无候选漏洞时跳过验证阶段
    has_findings: Callable[[], Awaitable[bool]]
    skip_stage: Callable[[str], Awaitable[None]]


class Orchestrator(Protocol):
    name: str

    async def run(self, stages: list[str], hooks: StageHooks) -> None: ...


class FixedOrchestrator:
    name = "fixed"

    async def run(self, stages: list[str], hooks: StageHooks) -> None:
        for index, stage in enumerate(stages):
            stage_id = await hooks.begin(stage)
            await hooks.execute(stage, stage_id)
            await hooks.complete(stage, stage_id)
            if index == 0:
                await hooks.after_environment_scan()


class StageState(TypedDict, total=False):
    completed: list[str]
    skip_verify: bool
    error: str
    failed_stage_id: int
    failed_stage_name: str


class LangGraphOrchestrator:
    name = "langgraph"

    async def run(self, stages: list[str], hooks: StageHooks) -> None:
        if not LANGGRAPH_AVAILABLE or StateGraph is None:
            raise RuntimeError("langgraph 未安装")

        graph = StateGraph(StageState)
        for index, stage_name in enumerate(stages):

            async def node(
                state: StageState, _stage: str = stage_name, _index: int = index
            ) -> StageState:
                if state.get("error"):
                    return {}
                try:
                    stage_id = await hooks.begin(_stage)
                    await hooks.execute(_stage, stage_id)
                except StageAborted as exc:
                    return {
                        "error": exc.message,
                        "failed_stage_id": exc.stage_id or 0,
                        "failed_stage_name": _stage,
                    }
                await hooks.complete(_stage, stage_id)
                if _index == 0:
                    await hooks.after_environment_scan()
                update: StageState = {
                    "completed": [*state.get("completed", []), _stage]
                }
                next_index = _index + 1
                if (
                    _stage == "code_analysis"
                    and next_index < len(stages)
                    and not await hooks.has_findings()
                ):
                    skipped_stage = stages[next_index]
                    await hooks.skip_stage(skipped_stage)
                    update["skip_verify"] = True
                    update["completed"] = [
                        *update["completed"],
                        skipped_stage,
                    ]
                return update

            graph.add_node(stage_name, node)

        graph.add_edge(START, stages[0])
        for index, stage_name in enumerate(stages):
            next_stage = stages[index + 1] if index + 1 < len(stages) else None
            skip_target = stages[index + 2] if index + 2 < len(stages) else None

            def route(
                state: StageState,
                _next: str | None = next_stage,
                _skip: str | None = skip_target,
            ) -> str:
                if state.get("error"):
                    return END  # type: ignore[return-value]
                if _skip and state.get("skip_verify"):
                    return _skip
                return _next or END  # type: ignore[return-value]

            mapping = {(next_stage or END): (next_stage or END), END: END}
            if skip_target:
                mapping[skip_target] = skip_target
            graph.add_conditional_edges(stage_name, route, mapping)

        compiled = graph.compile()
        result = await compiled.ainvoke(
            {"completed": []}, config={"recursion_limit": 20}
        )
        if result.get("error"):
            raise StageAborted(
                str(result["error"]),
                result.get("failed_stage_id") or None,
                str(result.get("failed_stage_name") or ""),
            )
