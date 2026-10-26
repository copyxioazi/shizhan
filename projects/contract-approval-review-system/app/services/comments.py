"""评论幂等回写。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from app.db import transaction
from app.errors import BlockedError, NotFoundError, UpstreamError
from app.status import ErrorCode, Stage, TaskStatus, WriteStatus
from app.services.upstream_client import get_upstream_client


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def comment_idempotency_key(approval_code: str, review_id: int) -> str:
    return f"contract-review:{approval_code}:{review_id}"


def _mark_task(task_id: int, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = _now()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    with transaction() as conn:
        conn.execute(
            f"UPDATE approval_tasks SET {assignments} WHERE id = ?",
            (*fields.values(), task_id),
        )


def _update_log(log_id: int, **fields) -> None:
    assignments = ", ".join(f"{key} = ?" for key in fields)
    with transaction() as conn:
        conn.execute(
            f"UPDATE comment_logs SET {assignments} WHERE id = ?",
            (*fields.values(), log_id),
        )


def write_comment(instance_id: str, review_id: int) -> dict:
    """用 contract-review:{approval_code}:{review_id} 幂等键写回评论区。"""
    with transaction() as conn:
        task_row = conn.execute(
            "SELECT * FROM approval_tasks WHERE approval_code = ?", (instance_id,)
        ).fetchone()
        if task_row is None:
            raise NotFoundError(
                f"审批任务尚未拉取: {instance_id}",
                code="TASK_NOT_FOUND",
                instance_id=instance_id,
            )
        review_row = conn.execute(
            "SELECT * FROM review_results WHERE id = ?", (review_id,)
        ).fetchone()
        if review_row is None or review_row["task_id"] != task_row["id"]:
            raise NotFoundError(
                f"审查结果与审批单不匹配: {review_id}",
                code="REVIEW_NOT_FOUND",
                review_id=review_id,
                instance_id=instance_id,
            )
        task = _row_to_dict(task_row)
        review = _row_to_dict(review_row)
        attempt_no = (
            conn.execute(
                "SELECT COUNT(*) FROM comment_logs WHERE task_id = ?",
                (task["id"],),
            ).fetchone()[0]
            + 1
        )

    idempotency_key = comment_idempotency_key(instance_id, review_id)

    # 本地已成功：直接短路，不再调用上游。
    if task["write_status"] == WriteStatus.SUCCESS.value:
        return {
            "instance_id": instance_id,
            "case_id": task["id"],
            "review_id": review_id,
            "write_status": WriteStatus.SUCCESS.value,
            "idempotency_key": idempotency_key,
            "duplicate": True,
            "short_circuited": True,
        }

    now = _now()
    with transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO comment_logs
                (task_id, write_status, write_response_text, created_at,
                 review_id, attempt_no, idempotency_key)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task["id"],
                WriteStatus.WRITING.value,
                None,
                now,
                review_id,
                attempt_no,
                idempotency_key,
            ),
        )
        log_id = cursor.lastrowid

    _mark_task(
        task["id"],
        write_status=WriteStatus.WRITING.value,
        stage=Stage.WRITE.value,
    )

    try:
        result = get_upstream_client().add_comment(
            instance_id, review["comment_text"], idempotency_key
        )
    except UpstreamError as exc:
        _update_log(
            log_id,
            write_status=WriteStatus.FAILED.value,
            write_response_text=json.dumps(
                {
                    "error": str(exc),
                    "code": exc.code,
                    "details": exc.details,
                },
                ensure_ascii=False,
            ),
            http_status=exc.details.get("upstream_status"),
            error_code=ErrorCode.COMMENT_WRITE_FAILED.value,
        )
        _mark_task(
            task["id"],
            write_status=WriteStatus.FAILED.value,
            task_status=TaskStatus.BLOCKED.value,
            stage=Stage.WRITE.value,
            last_error_code=ErrorCode.COMMENT_WRITE_FAILED.value,
            last_error=str(exc),
        )
        raise BlockedError(
            "审查意见回写失败",
            code=ErrorCode.COMMENT_WRITE_FAILED.value,
            instance_id=instance_id,
            review_id=review_id,
            reason=str(exc),
        ) from exc

    response_text = json.dumps(result, ensure_ascii=False)
    _update_log(
        log_id,
        write_status=WriteStatus.SUCCESS.value,
        write_response_text=response_text,
        http_status=200,
    )
    finished_at = _now()
    with transaction() as conn:
        conn.execute(
            """
            UPDATE approval_tasks
               SET write_status = ?, task_status = ?, stage = ?,
                   last_error_code = NULL, last_error = NULL,
                   finished_at = ?, updated_at = ?
             WHERE id = ?
            """,
            (
                WriteStatus.SUCCESS.value,
                TaskStatus.DONE.value,
                Stage.DONE.value,
                finished_at,
                finished_at,
                task["id"],
            ),
        )

    return {
        "instance_id": instance_id,
        "case_id": task["id"],
        "review_id": review_id,
        "comment_id": result.get("comment_id"),
        "write_status": WriteStatus.SUCCESS.value,
        "idempotency_key": idempotency_key,
        "duplicate": bool(result.get("duplicate")),
        "attempt_no": attempt_no,
        "finished_at": finished_at,
    }
