"""启动恢复测试。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db import transaction
from app.services.tasks import recover_interrupted_tasks

pytestmark = pytest.mark.integration


def _insert_task(
    approval_code: str,
    *,
    task_status: str,
    stage: str,
    write_status: str = "not_written",
    resume_stage: str | None = None,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO approval_tasks
                (approval_code, approval_title, applicant_name, task_status,
                 write_status, created_at, updated_at, stage, resume_stage)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                approval_code,
                f"恢复测试 {approval_code}",
                "测试",
                task_status,
                write_status,
                now,
                now,
                stage,
                resume_stage,
            ),
        )
        return cursor.lastrowid


def _task(task_id: int) -> dict:
    with transaction() as conn:
        row = conn.execute(
            "SELECT * FROM approval_tasks WHERE id = ?", (task_id,)
        ).fetchone()
    return {key: row[key] for key in row.keys()}


def test_recover_intermediate_states(live_server) -> None:
    parsing_id = _insert_task("REC-PARSING", task_status="parsing", stage="parse")
    writing_id = _insert_task(
        "REC-WRITING",
        task_status="reviewing",
        stage="write",
        write_status="writing",
        resume_stage="write",
    )
    queued_id = _insert_task(
        "REC-QUEUED",
        task_status="pending",
        stage="queued",
        resume_stage="review",
    )
    done_id = _insert_task(
        "REC-DONE",
        task_status="done",
        stage="done",
        write_status="success",
    )

    result = recover_interrupted_tasks()
    assert result["recovered"] == 3

    parsing = _task(parsing_id)
    assert parsing["task_status"] == "blocked"
    assert parsing["stage"] == "parse"
    assert parsing["last_error_code"] == "SERVICE_INTERRUPTED"

    writing = _task(writing_id)
    assert writing["task_status"] == "blocked"
    assert writing["write_status"] == "failed"
    assert writing["stage"] == "write"

    queued = _task(queued_id)
    assert queued["task_status"] == "blocked"
    assert queued["stage"] == "review"

    done = _task(done_id)
    assert done["task_status"] == "done"
    assert done["write_status"] == "success"

    with transaction() as conn:
        logs = conn.execute(
            "SELECT COUNT(*) FROM task_logs WHERE log_type = 'SERVICE_INTERRUPTED'"
        ).fetchone()[0]
    assert logs >= 3

    # 幂等：再次恢复没有可处理任务
    assert recover_interrupted_tasks()["recovered"] == 0
