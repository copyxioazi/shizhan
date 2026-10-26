import asyncio

import pytest

from app.orchestration.state import RunState
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


class FakeManager:
    async def ping(self) -> bool:
        return True

    async def image_exists(self, image: str) -> bool:
        return image == "ase-sandbox:1.0"


class FakeSandbox:
    container_name = "ase-sandbox-1-r1"
    image = "ase-sandbox:1.0"

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.bound: tuple[int | None, int | None] | None = None
        self.manager = FakeManager()

    def bind_worker(self, stage_id: int | None, worker_task_id: int | None) -> None:
        self.bound = (stage_id, worker_task_id)

    async def helper(self, args: list[str]) -> dict:
        self.calls.append(("helper", list(args)))
        return {"path": args[-1] if args else "", "content": "x" * 10, "count": 1}

    async def exec(self, argv: list[str]) -> dict:
        self.calls.append(("exec", list(argv)))
        return {"exit_code": 0, "stdout": "ok", "stderr": ""}

    async def stats(self) -> dict:
        return {"cpu_usage": 1.0, "memory_usage": 2.0}


def test_tool_executor_translates_helper_calls():
    sandbox = FakeSandbox()
    executor = ToolExecutor(sandbox)

    asyncio.run(executor.list_files(5))
    asyncio.run(executor.search_code("sql", max_hits=20))
    asyncio.run(executor.read_file("app.py"))
    asyncio.run(executor.syntax_check("/src/verify/sql_injection.py"))

    assert sandbox.calls == [
        ("helper", ["list", "--max-files", "5"]),
        ("helper", ["search", "sql", "--max-hits", "20"]),
        ("helper", ["read", "app.py"]),
        ("helper", ["syntax", "verify/sql_injection.py"]),
    ]


def test_tool_executor_routes_command_and_stats():
    sandbox = FakeSandbox()
    executor = ToolExecutor(sandbox)

    result = asyncio.run(executor.run_command(["python", "--version"]))
    stats = asyncio.run(executor.stats())

    assert result["exit_code"] == 0
    assert stats == {"cpu_usage": 1.0, "memory_usage": 2.0}
    assert sandbox.calls == [("exec", ["python", "--version"])]


def test_tool_trace_omits_source_content():
    sandbox = FakeSandbox()
    executor = ToolExecutor(sandbox)

    asyncio.run(executor.read_file("app.py"))

    assert len(executor.trace) == 1
    entry = executor.trace[0]
    assert entry["tool"] == "read_file"
    assert entry["result_bytes"] == 10
    assert "content" not in entry


def test_registry_exposes_only_safe_tools():
    registry = ToolRegistry(ToolExecutor(FakeSandbox()))
    names = {item["function"]["name"] for item in registry.openai_tools()}
    assert names == {"list_files", "read_file", "search_code", "syntax_check"}
    assert "run_command" not in names


def test_registry_dispatches_and_validates_arguments():
    sandbox = FakeSandbox()
    registry = ToolRegistry(ToolExecutor(sandbox))

    asyncio.run(registry.call("read_file", {"path": "app.py"}))
    assert sandbox.calls[-1] == ("helper", ["read", "app.py"])

    with pytest.raises(ValueError):
        asyncio.run(registry.call("read_file", {}))
    with pytest.raises(ValueError):
        asyncio.run(registry.call("run_command", {"argv": ["sh"]}))
    with pytest.raises(ValueError):
        asyncio.run(registry.call("list_files", {"max_files": 0}))


def test_run_state_tracks_stage_worker_and_snapshot():
    state = RunState(
        project_id=7,
        run_no=2,
        project_name="demo",
        task_content="检查注入",
        source_path="D:/demo",
    )
    state.enter_stage("code_analysis", 11)
    state.bind_worker(22)
    state.record_plan({"focus_areas": ["SQL 注入"]})
    state.record_findings(["VULN-001", "VULN-002"])
    state.sync_tokens(123)
    state.fail("boom")

    snapshot = state.snapshot()
    assert snapshot["stage_name"] == "code_analysis"
    assert snapshot["stage_id"] == 11
    assert snapshot["worker_task_id"] == 22
    assert snapshot["plan_focus_areas"] == ["SQL 注入"]
    assert snapshot["findings"] == 2
    assert snapshot["token_count"] == 123
    assert snapshot["error"] == "boom"
