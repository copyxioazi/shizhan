import asyncio

import pytest

from app.orchestration.orchestrator import (
    FixedOrchestrator,
    LangGraphOrchestrator,
    StageAborted,
    StageHooks,
)

STAGES = [
    "environment_scan",
    "code_analysis",
    "vulnerability_verify",
    "report_generate",
]


class Recorder:
    def __init__(
        self, fail_stage: str | None = None, findings: bool = True
    ) -> None:
        self.fail_stage = fail_stage
        self.findings = findings
        self.calls: list[tuple[str, str] | tuple[str]] = []
        self.after_env = 0

    async def begin(self, stage: str) -> int:
        self.calls.append(("begin", stage))
        return len(self.calls)

    async def execute(self, stage: str, stage_id: int) -> None:
        self.calls.append(("execute", stage))
        if stage == self.fail_stage:
            raise StageAborted(f"{stage} failed", stage_id, stage)

    async def complete(self, stage: str, stage_id: int) -> None:
        self.calls.append(("complete", stage))

    async def after_environment_scan(self) -> None:
        self.calls.append(("after_env",))
        self.after_env += 1

    async def has_findings(self) -> bool:
        return self.findings

    async def skip_stage(self, stage: str) -> None:
        self.calls.append(("skip", stage))


def _hooks(recorder: Recorder) -> StageHooks:
    return StageHooks(
        begin=recorder.begin,
        execute=recorder.execute,
        complete=recorder.complete,
        after_environment_scan=recorder.after_environment_scan,
        has_findings=recorder.has_findings,
        skip_stage=recorder.skip_stage,
    )


def _run_fixed(recorder: Recorder) -> None:
    asyncio.run(FixedOrchestrator().run(STAGES, _hooks(recorder)))


def _run_langgraph(recorder: Recorder) -> None:
    asyncio.run(LangGraphOrchestrator().run(STAGES, _hooks(recorder)))


def test_fixed_orchestrator_runs_stages_in_order():
    recorder = Recorder()
    _run_fixed(recorder)
    assert recorder.after_env == 1
    assert recorder.calls == [
        ("begin", "environment_scan"),
        ("execute", "environment_scan"),
        ("complete", "environment_scan"),
        ("after_env",),
        ("begin", "code_analysis"),
        ("execute", "code_analysis"),
        ("complete", "code_analysis"),
        ("begin", "vulnerability_verify"),
        ("execute", "vulnerability_verify"),
        ("complete", "vulnerability_verify"),
        ("begin", "report_generate"),
        ("execute", "report_generate"),
        ("complete", "report_generate"),
    ]


def test_fixed_orchestrator_stops_on_stage_failure():
    recorder = Recorder(fail_stage="code_analysis")
    with pytest.raises(StageAborted):
        _run_fixed(recorder)
    assert recorder.after_env == 1
    assert ("complete", "code_analysis") not in recorder.calls
    assert ("begin", "vulnerability_verify") not in recorder.calls


def test_langgraph_matches_fixed_orchestration():
    pytest.importorskip("langgraph")
    fixed = Recorder()
    graph = Recorder()
    _run_fixed(fixed)
    _run_langgraph(graph)
    assert graph.calls == fixed.calls
    assert graph.after_env == 1


def test_langgraph_stops_on_stage_failure():
    pytest.importorskip("langgraph")
    recorder = Recorder(fail_stage="vulnerability_verify")
    with pytest.raises(StageAborted) as exc_info:
        _run_langgraph(recorder)
    assert exc_info.value.stage_name == "vulnerability_verify"
    assert ("complete", "vulnerability_verify") not in recorder.calls
    assert ("begin", "report_generate") not in recorder.calls


def test_langgraph_skips_verify_when_no_findings():
    pytest.importorskip("langgraph")
    recorder = Recorder(findings=False)
    _run_langgraph(recorder)
    assert ("skip", "vulnerability_verify") in recorder.calls
    assert ("begin", "vulnerability_verify") not in recorder.calls
    assert ("begin", "report_generate") in recorder.calls


def test_fixed_always_runs_verify():
    recorder = Recorder(findings=False)
    _run_fixed(recorder)
    assert ("begin", "vulnerability_verify") in recorder.calls
    assert ("skip", "vulnerability_verify") not in recorder.calls
