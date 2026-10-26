"""待办拉取、去重与详情聚合。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from app.db import transaction
from app.errors import NotFoundError
from app.status import Stage, TaskStatus, WriteStatus
from app.services.attachments import get_attachments
from app.services.upstream_client import get_upstream_client


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def _task_summary(task: dict, *, created: bool = False) -> dict:
    return {
        "instance_id": task["approval_code"],
        "approval_code": task["approval_code"],
        "case_id": task["id"],
        "approval_title": task["approval_title"],
        "applicant_name": task["applicant_name"],
        "applied_at": task.get("applied_at"),
        "upstream_status": task.get("upstream_status"),
        "task_status": task["task_status"],
        "write_status": task["write_status"],
        "stage": task.get("stage"),
        "created": created,
    }


def _get_task_by_code(conn: sqlite3.Connection, approval_code: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM approval_tasks WHERE approval_code = ?", (approval_code,)
    ).fetchone()


def pull_pending(limit: int = 50) -> list[dict]:
    """调用上游待办接口，按 approval_code upsert 到 approval_tasks。"""
    items = get_upstream_client().list_pending(limit)
    results: list[dict] = []

    for item in items:
        approval_code = str(item.get("instance_id") or item.get("approval_code") or "")
        if not approval_code:
            continue
        now = _now()
        form_data_json = json.dumps(item.get("form_data") or {}, ensure_ascii=False)

        with transaction() as conn:
            existing = _get_task_by_code(conn, approval_code)
            if existing is not None:
                conn.execute(
                    """
                    UPDATE approval_tasks
                       SET approval_title = ?, applicant_name = ?, applied_at = ?,
                           form_data_json = ?, upstream_status = ?, updated_at = ?
                     WHERE id = ?
                    """,
                    (
                        item.get("approval_title") or existing["approval_title"],
                        item.get("applicant_name") or existing["applicant_name"],
                        item.get("applied_at") or existing["applied_at"],
                        form_data_json,
                        item.get("status"),
                        now,
                        existing["id"],
                    ),
                )
                task = _row_to_dict(
                    conn.execute(
                        "SELECT * FROM approval_tasks WHERE id = ?",
                        (existing["id"],),
                    ).fetchone()
                )
                results.append(_task_summary(task, created=False))
                continue

            cursor = conn.execute(
                """
                INSERT INTO approval_tasks
                    (approval_code, approval_title, applicant_name, task_status,
                     write_status, created_at, updated_at, applied_at,
                     form_data_json, upstream_status, stage)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval_code,
                    item.get("approval_title") or approval_code,
                    item.get("applicant_name") or "",
                    TaskStatus.PENDING.value,
                    WriteStatus.NOT_WRITTEN.value,
                    now,
                    now,
                    item.get("applied_at"),
                    form_data_json,
                    item.get("status"),
                    Stage.IDLE.value,
                ),
            )
            task = _row_to_dict(
                conn.execute(
                    "SELECT * FROM approval_tasks WHERE id = ?", (cursor.lastrowid,)
                ).fetchone()
            )
        results.append(_task_summary(task, created=True))

    return results


def get_detail(instance_id: str) -> dict:
    """合并上游详情与本地任务/附件/解析/审查状态。"""
    upstream = get_upstream_client().get_approval(instance_id)

    with transaction() as conn:
        task_row = _get_task_by_code(conn, instance_id)
        parse_row = None
        review_row = None
        if task_row is not None:
            parse_row = conn.execute(
                "SELECT * FROM contract_parses WHERE task_id = ?",
                (task_row["id"],),
            ).fetchone()
            review_row = conn.execute(
                "SELECT * FROM review_results WHERE task_id = ?",
                (task_row["id"],),
            ).fetchone()
            comment_count = conn.execute(
                "SELECT COUNT(*) FROM comment_logs WHERE task_id = ?",
                (task_row["id"],),
            ).fetchone()[0]
            task = _row_to_dict(task_row)
        else:
            task = None
            comment_count = 0

    local_attachments = get_attachments(task["id"]) if task is not None else []
    local_by_upstream = {
        str(row["upstream_attachment_id"]): row for row in local_attachments
    }
    merged_attachments = []
    for item in upstream.get("attachments", []):
        local = local_by_upstream.get(str(item["attachment_id"]))
        merged = dict(item)
        merged["document_id"] = local["id"] if local else None
        merged["download_status"] = (
            local["download_status"] if local else "not_downloaded"
        )
        merged["local_sha256"] = local["sha256"] if local else None
        merged["file_path"] = local["file_path"] if local else None
        merged["is_primary"] = bool(local["is_primary"]) if local else False
        merged_attachments.append(merged)

    parse_info = None
    if parse_row is not None:
        parse_info = {
            "document_id": parse_row["source_attachment_id"],
            "parse_status": parse_row["parse_status"],
            "parse_error": parse_row["parse_error"],
            "ocr_used": bool(parse_row["ocr_used"]),
            "page_count": parse_row["page_count"],
            "text_length": parse_row["text_length"],
            "warnings": json.loads(parse_row["warnings_json"] or "[]"),
        }

    review_info = None
    if review_row is not None:
        review_info = {
            "review_id": review_row["id"],
            "overall_risk_level": review_row["overall_risk_level"],
            "summary_text": review_row["summary_text"],
            "focus_points": json.loads(review_row["focus_points_json"] or "[]"),
            "comment_text": review_row["comment_text"],
        }

    if task is None:
        return {
            "instance_id": instance_id,
            "approval_code": instance_id,
            "approval_title": upstream.get("approval_title"),
            "applicant_name": upstream.get("applicant_name"),
            "applied_at": upstream.get("applied_at"),
            "upstream_status": upstream.get("status"),
            "form_data": upstream.get("form_data") or {},
            "attachments": merged_attachments,
            "pulled": False,
            "task": None,
            "case_id": None,
            "task_status": None,
            "write_status": None,
            "stage": None,
            "parse": None,
            "review": None,
            "comment_attempts": 0,
        }

    return {
        "instance_id": instance_id,
        "approval_code": instance_id,
        "approval_title": upstream.get("approval_title") or task["approval_title"],
        "applicant_name": upstream.get("applicant_name") or task["applicant_name"],
        "applied_at": upstream.get("applied_at") or task.get("applied_at"),
        "upstream_status": upstream.get("status"),
        "form_data": upstream.get("form_data") or {},
        "attachments": merged_attachments,
        "pulled": True,
        "task": task,
        "case_id": task["id"],
        "task_status": task["task_status"],
        "write_status": task["write_status"],
        "stage": task.get("stage"),
        "last_error_code": task.get("last_error_code"),
        "last_error": task.get("last_error"),
        "retry_count": task.get("retry_count", 0),
        "parse": parse_info,
        "review": review_info,
        "comment_attempts": comment_count,
    }


def get_task_or_404(instance_id: str) -> dict:
    with transaction() as conn:
        row = _get_task_by_code(conn, instance_id)
    if row is None:
        raise NotFoundError(
            f"审批任务尚未拉取: {instance_id}",
            code="TASK_NOT_FOUND",
            instance_id=instance_id,
        )
    return _row_to_dict(row)
