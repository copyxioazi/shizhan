"""可恢复审查流水线。

阶段顺序：download -> parse -> review -> save -> write -> done。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.db import transaction
from app.errors import BlockedError, UpstreamError
from app.services import attachments as attachment_service
from app.services import approvals as approval_service
from app.services import comments as comment_service
from app.services import review as review_service
from app.services.logs import log_task
from app.services.parser.service import parse_document
from app.services.rules.engine import run_rules
from app.status import ErrorCode, Stage, TaskStatus, WriteStatus

if TYPE_CHECKING:
    from app.services.queue import Job


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def _get_task(task_id: int) -> dict | None:
    with transaction() as conn:
        row = conn.execute(
            "SELECT * FROM approval_tasks WHERE id = ?", (task_id,)
        ).fetchone()
    return _row_to_dict(row) if row is not None else None


def _set_state(
    task_id: int,
    *,
    task_status: str,
    stage: str,
    clear_error: bool = True,
) -> None:
    fields = {
        "task_status": task_status,
        "stage": stage,
        "updated_at": _now(),
    }
    if clear_error:
        fields["last_error_code"] = None
        fields["last_error"] = None
    assignments = ", ".join(f"{key} = ?" for key in fields)
    with transaction() as conn:
        conn.execute(
            f"UPDATE approval_tasks SET {assignments} WHERE id = ?",
            (*fields.values(), task_id),
        )


def _block(task_id: int, stage: str, code: str, message: str, *, write_failed: bool = False) -> None:
    with transaction() as conn:
        conn.execute(
            """
            UPDATE approval_tasks
               SET task_status = ?, stage = ?, last_error_code = ?, last_error = ?,
                   write_status = CASE WHEN ? = 1 THEN 'failed' ELSE write_status END,
                   updated_at = ?
             WHERE id = ?
            """,
            (
                TaskStatus.BLOCKED.value,
                stage,
                code,
                message,
                1 if write_failed else 0,
                _now(),
                task_id,
            ),
        )


def _get_parse_status(task_id: int) -> str | None:
    with transaction() as conn:
        row = conn.execute(
            "SELECT parse_status FROM contract_parses WHERE task_id = ?", (task_id,)
        ).fetchone()
    return row["parse_status"] if row is not None else None


def _latest_review_id(task_id: int) -> int | None:
    with transaction() as conn:
        row = conn.execute(
            "SELECT id FROM review_results WHERE task_id = ?", (task_id,)
        ).fetchone()
    return row["id"] if row is not None else None


def _load_hits(task_id: int) -> list[dict]:
    with transaction() as conn:
        rows = conn.execute(
            """
            SELECT h.*, r.rule_code, r.category, r.sort_order
              FROM rule_hits h
              JOIN review_rules r ON r.id = h.rule_id
             WHERE h.task_id = ? AND h.hit_status = 'hit'
             ORDER BY r.sort_order ASC, r.id ASC
            """,
            (task_id,),
        ).fetchall()
    hits: list[dict] = []
    for row in rows:
        hits.append(
            {
                "rule_id": row["rule_id"],
                "rule_code": row["rule_code"],
                "rule_name": row["rule_name_snapshot"],
                "risk_level": row["risk_level_snapshot"],
                "category": row["category"],
                "suggestion_text": row["suggestion_snapshot"],
                "sort_order": row["sort_order"] or 0,
                "evidence_text": row["evidence_text"],
                "position": json.loads(row["evidence_position"] or "{}"),
                "matched_value": row["matched_value"],
            }
        )
    return hits


def _download_all(task: dict) -> None:
    approval_code = task["approval_code"]
    detail = approval_service.get_detail(approval_code)
    attachments = detail.get("attachments") or []
    if not attachments:
        raise BlockedError(
            "审批单没有附件",
            code=ErrorCode.MISSING_ATTACHMENT.value,
            instance_id=approval_code,
        )
    for item in attachments:
        attachment_service.download_attachment(
            approval_code, item["attachment_id"], item["file_name"]
        )


def _pick_primary(task: dict, *, mark: bool = False) -> dict:
    attachments = attachment_service.get_attachments(task["id"])
    primary = attachment_service.select_primary_attachment(attachments)
    if primary is None:
        raise BlockedError(
            "没有可解析的主附件",
            code=ErrorCode.MISSING_ATTACHMENT.value,
            case_id=task["id"],
        )
    if mark:
        attachment_service.mark_primary(task["id"], primary["id"])
    return primary


def _failure_code(stage: str) -> str:
    return {
        "download": ErrorCode.DOWNLOAD_FAILED.value,
        "parse": ErrorCode.PARSE_FAILED.value,
        "review": ErrorCode.SAVE_FAILED.value,
        "save": ErrorCode.SAVE_FAILED.value,
        "write": ErrorCode.COMMENT_WRITE_FAILED.value,
    }.get(stage, ErrorCode.SAVE_FAILED.value)


def run_pipeline_sync(job: "Job") -> None:
    """在 worker 线程中执行完整流水线；异常应转 blocked 并落库。"""
    task = _get_task(job.task_id)
    if task is None:
        log_task(None, "ERROR", "PIPELINE", f"任务不存在：{job.task_id}")
        return

    task_id = task["id"]
    approval_code = task["approval_code"]
    stage = job.resume_stage or "download"
    parse_status = _get_parse_status(task_id)

    with transaction() as conn:
        conn.execute(
            """
            UPDATE approval_tasks
               SET retry_count = ?, stage = ?, started_at = COALESCE(started_at, ?),
                   queued_at = COALESCE(queued_at, ?), last_error_code = NULL,
                   last_error = NULL, updated_at = ?
             WHERE id = ?
            """,
            (job.retry_count, stage, _now(), _now(), _now(), task_id),
        )

    log_task(
        task_id,
        "INFO",
        "PIPELINE_START",
        f"开始审查：stage={stage}, retry={job.retry_count}",
        stage=stage,
    )

    try:
        if stage == "download":
            _set_state(
                task_id,
                task_status=TaskStatus.PARSING.value,
                stage=Stage.DOWNLOAD.value,
            )
            _download_all(task)
            primary = _pick_primary(task, mark=True)
            stage = "parse"

        if stage == "parse":
            _set_state(
                task_id,
                task_status=TaskStatus.PARSING.value,
                stage=Stage.PARSE.value,
            )
            primary = _pick_primary(task, mark=True)
            parsed = parse_document(primary["id"])
            parse_status = parsed["parse_status"]
            stage = "review"

        if stage == "review":
            if parse_status is None or parse_status == "failed":
                raise BlockedError(
                    "缺少可用解析结果，请从解析阶段重试",
                    code=ErrorCode.PARSE_FAILED.value,
                )
            _set_state(
                task_id,
                task_status=TaskStatus.REVIEWING.value,
                stage=Stage.REVIEW.value,
            )
            result = run_rules(task_id)
            hits = result["hits"]
            stage = "save"
        else:
            hits = _load_hits(task_id)

        if stage == "save":
            if parse_status is None:
                raise BlockedError(
                    "缺少解析结果，无法生成审查结论",
                    code=ErrorCode.SAVE_FAILED.value,
                )
            _set_state(
                task_id,
                task_status=TaskStatus.REVIEWING.value,
                stage=Stage.SAVE.value,
            )
            built = review_service.build_review(hits, parse_status)
            saved = review_service.save_review(task_id, built)
            review_id = saved["review_id"]
            stage = "write"
        else:
            review_id = _latest_review_id(task_id)

        if stage == "write":
            if review_id is None:
                raise BlockedError(
                    "缺少审查结果，无法回写评论",
                    code=ErrorCode.SAVE_FAILED.value,
                )
            _set_state(
                task_id,
                task_status=TaskStatus.REVIEWING.value,
                stage=Stage.WRITE.value,
            )
            comment_service.write_comment(approval_code, review_id)

        log_task(
            task_id,
            "INFO",
            "PIPELINE_DONE",
            "审查流水线完成",
            stage=Stage.DONE.value,
        )
    except BlockedError as exc:
        # 工具通常已写状态；这里兜底保证异常路径也不会卡在中间态。
        _block(
            task_id,
            stage,
            exc.code,
            exc.message,
            write_failed=stage == "write",
        )
        log_task(
            task_id,
            "ERROR",
            "PIPELINE_BLOCKED",
            f"{stage} 阶段阻塞：{exc.code} · {exc.message}",
            stage=stage,
            detail={"code": exc.code, "details": exc.details},
        )
    except UpstreamError as exc:
        _block(
            task_id,
            stage,
            ErrorCode.UPSTREAM_UNAVAILABLE.value,
            str(exc),
            write_failed=stage == "write",
        )
        log_task(
            task_id,
            "ERROR",
            "PIPELINE_BLOCKED",
            f"上游不可用：{exc}",
            stage=stage,
        )
    except Exception as exc:  # noqa: BLE001 - 任何异常都不能让任务卡在中间态
        _block(
            task_id,
            stage,
            _failure_code(stage),
            str(exc),
            write_failed=stage == "write",
        )
        log_task(
            task_id,
            "ERROR",
            "PIPELINE_BLOCKED",
            f"{stage} 阶段异常：{exc}",
            stage=stage,
        )
