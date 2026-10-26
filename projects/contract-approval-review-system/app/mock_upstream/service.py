"""Mock 审批系统数据库操作。

Mock 库与本地审查库物理隔离；本模块只做数据读写，不导入本地服务。
HTTP 层通过 ``MockUpstreamError`` 把业务失败翻译成上游状态码。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.config import BASE_DIR, settings
from app.db import transaction

FAULT_SCOPES = {"detail", "download", "comment"}


class MockUpstreamError(Exception):
    """表示 Mock 上游返回的错误响应。"""

    def __init__(self, status_code: int, code: str, message: str, **details) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def _safe_json(value: str | None) -> dict:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _resolve_path(stored_path: str) -> Path:
    path = Path(stored_path)
    return path if path.is_absolute() else BASE_DIR / path


def _check_fault(scope: str) -> None:
    """故障注入：detail/download/comment 任一开启时直接返回错误。"""
    if scope not in FAULT_SCOPES:
        return
    with transaction(settings.mock_db_path) as conn:
        row = conn.execute(
            "SELECT enabled, http_status FROM upstream_faults WHERE scope = ?",
            (scope,),
        ).fetchone()
    if row is not None and row["enabled"]:
        raise MockUpstreamError(
            int(row["http_status"] or 500),
            f"MOCK_FAULT_{scope.upper()}",
            f"Mock 上游故障注入已开启：{scope}",
        )


def _attachment_dict(row: sqlite3.Row, approval_code: str) -> dict:
    path = _resolve_path(row["stored_path"])
    return {
        "attachment_id": row["id"],
        "file_name": row["file_name"],
        "file_type": row["file_type"],
        "file_size": row["file_size"],
        "sha256": row["sha256"],
        "sort_order": row["sort_order"],
        "available": bool(row["available"]) and path.is_file(),
        "download_url": (
            f"/mock-upstream/approvals/{approval_code}"
            f"/attachments/{row['id']}/file"
        ),
    }


def list_pending(limit: int = 50) -> list[dict]:
    with transaction(settings.mock_db_path) as conn:
        rows = conn.execute(
            """
            SELECT a.*,
                   (SELECT COUNT(*) FROM upstream_attachments u
                     WHERE u.approval_code = a.approval_code) AS attachment_count
              FROM upstream_approvals a
             WHERE a.status = 'pending'
             ORDER BY a.applied_at DESC, a.approval_code ASC
             LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "instance_id": row["approval_code"],
            "approval_code": row["approval_code"],
            "approval_title": row["approval_title"],
            "applicant_name": row["applicant_name"],
            "applied_at": row["applied_at"],
            "status": row["status"],
            "form_data": _safe_json(row["form_data_json"]),
            "attachment_count": row["attachment_count"],
        }
        for row in rows
    ]


def get_approval(instance_id: str) -> dict:
    _check_fault("detail")
    with transaction(settings.mock_db_path) as conn:
        row = conn.execute(
            "SELECT * FROM upstream_approvals WHERE approval_code = ?",
            (instance_id,),
        ).fetchone()
        if row is None:
            raise MockUpstreamError(404, "APPROVAL_NOT_FOUND", "审批单不存在")
        attachments = conn.execute(
            """
            SELECT * FROM upstream_attachments
             WHERE approval_code = ?
             ORDER BY sort_order ASC, id ASC
            """,
            (instance_id,),
        ).fetchall()
    return {
        "instance_id": row["approval_code"],
        "approval_code": row["approval_code"],
        "approval_title": row["approval_title"],
        "applicant_name": row["applicant_name"],
        "applied_at": row["applied_at"],
        "status": row["status"],
        "form_data": _safe_json(row["form_data_json"]),
        "attachments": [
            _attachment_dict(item, row["approval_code"]) for item in attachments
        ],
    }


def get_attachment_file(instance_id: str, attachment_id: int) -> dict:
    _check_fault("download")
    with transaction(settings.mock_db_path) as conn:
        row = conn.execute(
            """
            SELECT * FROM upstream_attachments
             WHERE id = ? AND approval_code = ?
            """,
            (attachment_id, instance_id),
        ).fetchone()
    if row is None or not row["available"]:
        raise MockUpstreamError(
            404, "ATTACHMENT_NOT_FOUND", "附件不存在或不可下载",
            attachment_id=attachment_id,
        )
    path = _resolve_path(row["stored_path"])
    if not path.is_file():
        raise MockUpstreamError(
            404, "ATTACHMENT_NOT_FOUND", "附件文件缺失",
            attachment_id=attachment_id,
        )
    return {
        "path": str(path),
        "file_name": row["file_name"],
        "file_type": row["file_type"],
        "file_size": row["file_size"],
        "sha256": row["sha256"],
        "attachment_id": row["id"],
        "approval_code": row["approval_code"],
    }


def add_comment(instance_id: str, content: str, idempotency_key: str) -> dict:
    _check_fault("comment")
    if not content.strip():
        raise MockUpstreamError(422, "EMPTY_COMMENT", "评论内容不能为空")
    now = _now()
    with transaction(settings.mock_db_path) as conn:
        approval = conn.execute(
            "SELECT approval_code FROM upstream_approvals WHERE approval_code = ?",
            (instance_id,),
        ).fetchone()
        if approval is None:
            raise MockUpstreamError(404, "APPROVAL_NOT_FOUND", "审批单不存在")

        existing = conn.execute(
            "SELECT * FROM upstream_comments WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            return {
                "comment_id": existing["id"],
                "instance_id": existing["approval_code"],
                "content": existing["content"],
                "idempotency_key": existing["idempotency_key"],
                "created_at": existing["created_at"],
                "duplicate": True,
            }

        cursor = conn.execute(
            """
            INSERT INTO upstream_comments
                (approval_code, content, idempotency_key, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (instance_id, content, idempotency_key, now),
        )
        comment_id = cursor.lastrowid
    return {
        "comment_id": comment_id,
        "instance_id": instance_id,
        "content": content,
        "idempotency_key": idempotency_key,
        "created_at": now,
        "duplicate": False,
    }


def list_comments(instance_id: str) -> list[dict]:
    with transaction(settings.mock_db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM upstream_comments
             WHERE approval_code = ?
             ORDER BY id ASC
            """,
            (instance_id,),
        ).fetchall()
    return [
        {
            "comment_id": row["id"],
            "instance_id": row["approval_code"],
            "content": row["content"],
            "idempotency_key": row["idempotency_key"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def restore_attachment(attachment_id: int) -> dict:
    with transaction(settings.mock_db_path) as conn:
        row = conn.execute(
            "SELECT * FROM upstream_attachments WHERE id = ?",
            (attachment_id,),
        ).fetchone()
        if row is None:
            raise MockUpstreamError(
                404, "ATTACHMENT_NOT_FOUND", "附件不存在",
                attachment_id=attachment_id,
            )
        path = _resolve_path(row["stored_path"])
        if not path.is_file():
            raise MockUpstreamError(
                404, "ATTACHMENT_FILE_MISSING", "附件文件不存在，无法恢复",
                attachment_id=attachment_id,
            )
        conn.execute(
            "UPDATE upstream_attachments SET available = 1, updated_at = ? WHERE id = ?",
            (_now(), attachment_id),
        )
    return {
        "attachment_id": attachment_id,
        "approval_code": row["approval_code"],
        "file_name": row["file_name"],
        "available": True,
        "sha256": row["sha256"],
    }


def set_fault(scope: str, enabled: bool, http_status: int = 500) -> dict:
    if scope not in FAULT_SCOPES:
        raise MockUpstreamError(422, "INVALID_SCOPE", f"不支持的故障范围: {scope}")
    with transaction(settings.mock_db_path) as conn:
        conn.execute(
            """
            INSERT INTO upstream_faults (scope, enabled, http_status)
            VALUES (?, ?, ?)
            ON CONFLICT(scope) DO UPDATE SET
                enabled = excluded.enabled,
                http_status = excluded.http_status
            """,
            (scope, 1 if enabled else 0, int(http_status)),
        )
    return {"scope": scope, "enabled": bool(enabled), "http_status": int(http_status)}


def reset() -> dict:
    """清空 Mock 数据并重新写入 4 个种子审批单。"""
    from app.mock_upstream.seed import seed_mock_data

    for table in (
        "upstream_comments",
        "upstream_faults",
        "upstream_attachments",
        "upstream_approvals",
    ):
        with transaction(settings.mock_db_path) as conn:
            conn.execute(f"DELETE FROM {table}")
    with transaction(settings.mock_db_path) as conn:
        conn.execute(
            "DELETE FROM sqlite_sequence WHERE name IN "
            "('upstream_comments','upstream_attachments')"
        )
    return seed_mock_data(reset=False)
