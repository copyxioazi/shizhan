"""任务查询、入队、重试与启动恢复。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from app.db import transaction
from app.errors import NotFoundError, ToolError
from app.services.logs import log_task
from app.services.queue import Job, get_queue_manager
from app.status import ErrorCode, Stage, TaskStatus, WriteStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def list_tasks() -> list[dict]:
    try:
        with transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM approval_tasks ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        return [_row_to_dict(row) for row in rows]
    except sqlite3.OperationalError:
        # 尚未执行 scripts/init_db.py 时返回空列表，保证框架可启动。
        return []


def get_task(task_id: int) -> dict:
    with transaction() as conn:
        row = conn.execute(
            "SELECT * FROM approval_tasks WHERE id = ?", (task_id,)
        ).fetchone()
    if row is None:
        raise NotFoundError(f"审批任务不存在: {task_id}", code="TASK_NOT_FOUND", task_id=task_id)
    return _row_to_dict(row)


def get_task_status(task_id: int) -> dict:
    task = get_task(task_id)
    return {
        "task_id": task["id"],
        "task_status": task["task_status"],
        "write_status": task["write_status"],
        "stage": task.get("stage"),
        "resume_stage": task.get("resume_stage"),
        "retry_count": task.get("retry_count", 0),
        "last_error_code": task.get("last_error_code"),
        "last_error": task.get("last_error"),
        "queued_at": task.get("queued_at"),
        "started_at": task.get("started_at"),
        "finished_at": task.get("finished_at"),
        "updated_at": task.get("updated_at"),
        "terminal": task["task_status"] in {TaskStatus.DONE.value, TaskStatus.BLOCKED.value},
    }


def _set_queued(task_id: int, resume_stage: str, retry_count: int) -> None:
    with transaction() as conn:
        conn.execute(
            """
            UPDATE approval_tasks
               SET task_status = ?, stage = ?, resume_stage = ?, retry_count = ?,
                   queued_at = ?, last_error_code = NULL, last_error = NULL,
                   updated_at = ?
             WHERE id = ?
            """,
            (
                TaskStatus.PENDING.value,
                Stage.QUEUED.value,
                resume_stage,
                retry_count,
                _now(),
                _now(),
                task_id,
            ),
        )


def _enqueue(task_id: int, resume_stage: str, retry_count: int) -> bool:
    manager = get_queue_manager()
    job = Job(task_id=task_id, resume_stage=resume_stage, retry_count=retry_count)
    return manager.enqueue_sync(job)


def enqueue_full_review(task_id: int) -> dict:
    task = get_task(task_id)
    if task["task_status"] == TaskStatus.DONE.value:
        return {
            "task_id": task_id,
            "queued": False,
            "reason": "already_done",
            "status": get_task_status(task_id),
        }
    if task["task_status"] in {
        TaskStatus.PARSING.value,
        TaskStatus.REVIEWING.value,
    } or (task["task_status"] == TaskStatus.PENDING.value and task["stage"] == Stage.QUEUED.value):
        return {
            "task_id": task_id,
            "queued": False,
            "reason": "already_in_progress",
            "status": get_task_status(task_id),
        }
    if task["task_status"] == TaskStatus.BLOCKED.value:
        return {
            "task_id": task_id,
            "queued": False,
            "reason": "blocked_use_retry",
            "status": get_task_status(task_id),
        }

    _set_queued(task_id, Stage.DOWNLOAD.value, 0)
    queued = _enqueue(task_id, Stage.DOWNLOAD.value, 0)
    return {
        "task_id": task_id,
        "queued": queued,
        "reason": None if queued else "duplicate_inflight",
        "resume_stage": Stage.DOWNLOAD.value,
        "status": get_task_status(task_id),
    }


def _retry_stage(task: dict) -> str:
    if task["stage"] == Stage.WRITE.value or task["write_status"] in {
        WriteStatus.FAILED.value,
        WriteStatus.WRITING.value,
    }:
        return Stage.WRITE.value
    if task["stage"] in {
        Stage.DOWNLOAD.value,
        Stage.PARSE.value,
        Stage.REVIEW.value,
        Stage.SAVE.value,
    }:
        return task["stage"]
    return Stage.DOWNLOAD.value


def enqueue_retry(task_id: int) -> dict:
    task = get_task(task_id)
    if task["task_status"] != TaskStatus.BLOCKED.value:
        raise ToolError(
            "只有阻塞任务可以重试",
            code="TASK_NOT_BLOCKED",
            task_id=task_id,
            task_status=task["task_status"],
        )

    resume_stage = _retry_stage(task)
    retry_count = int(task.get("retry_count") or 0) + 1
    _set_queued(task_id, resume_stage, retry_count)
    queued = _enqueue(task_id, resume_stage, retry_count)
    return {
        "task_id": task_id,
        "queued": queued,
        "reason": None if queued else "duplicate_inflight",
        "resume_stage": resume_stage,
        "retry_count": retry_count,
        "status": get_task_status(task_id),
    }


def recover_interrupted_tasks() -> dict:
    """启动时把中间态与排队任务转 blocked，等待人工重试。"""
    now = _now()
    sql = """
        UPDATE approval_tasks
           SET task_status = 'blocked',
               stage = CASE WHEN stage = 'queued'
                            THEN COALESCE(resume_stage, 'download')
                            ELSE stage END,
               write_status = CASE WHEN write_status = 'writing'
                                   THEN 'failed' ELSE write_status END,
               last_error_code = ?,
               last_error = ?,
               updated_at = ?
         WHERE task_status IN ('parsing', 'reviewing')
            OR write_status = 'writing'
            OR (task_status = 'pending' AND stage = 'queued')
    """
    try:
        with transaction() as conn:
            rows = conn.execute(
                """
                SELECT id FROM approval_tasks
                 WHERE task_status IN ('parsing', 'reviewing')
                    OR write_status = 'writing'
                    OR (task_status = 'pending' AND stage = 'queued')
                """
            ).fetchall()
            conn.execute(
                sql,
                (
                    ErrorCode.SERVICE_INTERRUPTED.value,
                    "service interrupted",
                    now,
                ),
            )
    except sqlite3.OperationalError as exc:
        # 全新目录尚未执行 scripts/init_db.py 时，空库也应能启动。
        if "no such table" in str(exc).lower():
            return {"recovered": 0, "skipped": "database not initialized"}
        raise
    for row in rows:
        log_task(
            row["id"],
            "WARN",
            "SERVICE_INTERRUPTED",
            "服务重启，任务已转为 blocked，请人工重试",
            detail={"error_code": ErrorCode.SERVICE_INTERRUPTED.value},
        )
    return {"recovered": len(rows)}
