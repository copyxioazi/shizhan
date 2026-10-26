"""附件下载、校验、存储与主附件选择。"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.config import BASE_DIR, settings
from app.db import transaction
from app.errors import BlockedError, NotFoundError, UpstreamError
from app.status import DownloadStatus, ErrorCode, Stage, TaskStatus
from app.services.upstream_client import get_upstream_client

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".png", ".jpg", ".jpeg"}

FILE_TYPES = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "docx",
    ".png": "png",
    ".jpg": "jpg",
    ".jpeg": "jpeg",
}

_UNSAFE_CHARS = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def safe_filename(file_name: str, fallback: str = "attachment") -> str:
    """去掉目录部分与非法字符，防止路径穿越。"""
    name = Path(str(file_name or "")).name
    name = _UNSAFE_CHARS.sub("_", name).strip().strip(".")
    return name or fallback


def local_attachment_path(
    approval_code: str, attachment_id: int, file_name: str
) -> Path:
    """返回安全的本地附件路径：data/attachments/<approval_code>/<id>_<name>。"""
    code_dir = safe_filename(approval_code, fallback="approval")
    target_dir = (settings.data_dir / "attachments" / code_dir).resolve()
    base = (settings.data_dir / "attachments").resolve()
    if base not in target_dir.parents and target_dir != base:
        raise ValueError(f"非法审批编号路径: {approval_code}")
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = safe_filename(file_name, fallback=f"attachment_{attachment_id}")
    return target_dir / f"{attachment_id}_{safe_name}"


def file_type_of(file_name: str) -> str:
    return FILE_TYPES.get(Path(file_name).suffix.lower(), "unknown")


def _relative_to_base(path: Path) -> str:
    try:
        return path.resolve().relative_to(BASE_DIR).as_posix()
    except ValueError:
        return str(path.resolve())


def resolve_stored_path(stored_path: str | None) -> Path | None:
    if not stored_path:
        return None
    path = Path(stored_path)
    return path if path.is_absolute() else BASE_DIR / path


def get_task_by_approval_code(conn: sqlite3.Connection, approval_code: str) -> dict:
    row = conn.execute(
        "SELECT * FROM approval_tasks WHERE approval_code = ?", (approval_code,)
    ).fetchone()
    if row is None:
        raise NotFoundError(
            f"审批任务尚未拉取: {approval_code}", code="TASK_NOT_FOUND",
            instance_id=approval_code,
        )
    return _row_to_dict(row)


def get_attachments(task_id: int) -> list[dict]:
    with transaction() as conn:
        rows = conn.execute(
            """
            SELECT * FROM approval_attachments
             WHERE task_id = ?
             ORDER BY sort_order ASC, id ASC
            """,
            (task_id,),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_attachment(document_id: int) -> dict:
    with transaction() as conn:
        row = conn.execute(
            "SELECT * FROM approval_attachments WHERE id = ?", (document_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(
                f"附件不存在: {document_id}", code="ATTACHMENT_NOT_FOUND",
                document_id=document_id,
            )
        task = conn.execute(
            "SELECT approval_code FROM approval_tasks WHERE id = ?",
            (row["task_id"],),
        ).fetchone()
    result = _row_to_dict(row)
    result["approval_code"] = task["approval_code"] if task is not None else None
    return result


def _update_attachment(
    document_id: int,
    *,
    download_status: str,
    file_path: str | None = None,
    sha256: str | None = None,
    file_size: int | None = None,
    download_error: str | None = None,
) -> None:
    with transaction() as conn:
        conn.execute(
            """
            UPDATE approval_attachments
               SET download_status = ?, file_path = COALESCE(?, file_path),
                   sha256 = COALESCE(?, sha256), file_size = COALESCE(?, file_size),
                   download_error = ?, updated_at = ?
             WHERE id = ?
            """,
            (
                download_status,
                file_path,
                sha256,
                file_size,
                download_error,
                _now(),
                document_id,
            ),
        )


def _ensure_local_row(
    task_id: int,
    attachment_id: int,
    file_name: str,
    *,
    file_type: str | None = None,
    sort_order: int = 0,
) -> dict:
    upstream_id = str(attachment_id)
    safe_name = safe_filename(file_name, fallback=f"attachment_{attachment_id}")
    resolved_type = file_type or file_type_of(file_name)
    with transaction() as conn:
        row = conn.execute(
            """
            SELECT * FROM approval_attachments
             WHERE task_id = ? AND upstream_attachment_id = ?
            """,
            (task_id, upstream_id),
        ).fetchone()
        if row is not None:
            # 上游元数据可能比首次入库更完整，补齐排序与文件类型。
            conn.execute(
                """
                UPDATE approval_attachments
                   SET file_name = ?, file_type = ?, sort_order = ?, updated_at = ?
                 WHERE id = ?
                """,
                (safe_name, resolved_type, sort_order, _now(), row["id"]),
            )
            row = conn.execute(
                "SELECT * FROM approval_attachments WHERE id = ?", (row["id"],)
            ).fetchone()
            return _row_to_dict(row)
        now = _now()
        cursor = conn.execute(
            """
            INSERT INTO approval_attachments
                (task_id, file_name, file_type, download_status, created_at,
                 upstream_attachment_id, file_size, sort_order, is_primary, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, 0, ?)
            """,
            (
                task_id,
                safe_name,
                resolved_type,
                DownloadStatus.PENDING.value,
                now,
                upstream_id,
                sort_order,
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM approval_attachments WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return _row_to_dict(row)


def _refresh_primary(task_id: int) -> dict | None:
    attachments = get_attachments(task_id)
    primary = select_primary_attachment(attachments)
    mark_primary(task_id, primary["id"] if primary else None)
    return primary


def _mark_task_blocked(task_id: int, code: str, message: str) -> None:
    """附件失败统一阻塞任务，保留失败阶段供人工重试。"""
    with transaction() as conn:
        conn.execute(
            """
            UPDATE approval_tasks
               SET task_status = ?, stage = ?, last_error_code = ?, last_error = ?,
                   updated_at = ?
             WHERE id = ? AND task_status != ?
            """,
            (
                TaskStatus.BLOCKED.value,
                Stage.DOWNLOAD.value,
                code,
                message,
                _now(),
                task_id,
                TaskStatus.DONE.value,
            ),
        )


def download_attachment(
    instance_id: str, attachment_id: int, file_name: str
) -> dict:
    """下载附件，校验 SHA-256，落到 data/attachments/<approval_code>/。"""
    with transaction() as conn:
        task = get_task_by_approval_code(conn, instance_id)

    # 从上游详情补齐 sort_order/file_type，主附件选择依赖上游排序。
    upstream_meta: dict | None = None
    try:
        detail = get_upstream_client().get_approval(instance_id)
        upstream_meta = next(
            (
                item
                for item in detail.get("attachments", [])
                if str(item.get("attachment_id")) == str(attachment_id)
            ),
            None,
        )
    except UpstreamError:
        # 详情接口故障不应阻断单独调用的下载工具。
        upstream_meta = None

    resolved_name = (upstream_meta or {}).get("file_name") or file_name
    local = _ensure_local_row(
        task["id"],
        attachment_id,
        resolved_name,
        file_type=(upstream_meta or {}).get("file_type"),
        sort_order=int((upstream_meta or {}).get("sort_order") or 0),
    )
    document_id = local["id"]

    try:
        content, upstream_checksum, _content_type = get_upstream_client().download_attachment(
            instance_id, attachment_id
        )
    except UpstreamError as exc:
        if exc.code in {"ATTACHMENT_NOT_FOUND", "HTTP_404"}:
            _update_attachment(
                document_id,
                download_status=DownloadStatus.MISSING.value,
                download_error="附件不存在或不可下载",
            )
            _mark_task_blocked(
                task["id"], ErrorCode.MISSING_ATTACHMENT.value, "附件不存在或不可下载"
            )
            raise BlockedError(
                "附件不存在或不可下载",
                code=ErrorCode.MISSING_ATTACHMENT.value,
                instance_id=instance_id,
                attachment_id=attachment_id,
            ) from exc
        _update_attachment(
            document_id,
            download_status=DownloadStatus.FAILED.value,
            download_error=str(exc),
        )
        _mark_task_blocked(task["id"], ErrorCode.DOWNLOAD_FAILED.value, str(exc))
        raise BlockedError(
            "附件下载失败",
            code=ErrorCode.DOWNLOAD_FAILED.value,
            instance_id=instance_id,
            attachment_id=attachment_id,
            reason=str(exc),
        ) from exc

    if not content:
        _update_attachment(
            document_id,
            download_status=DownloadStatus.FAILED.value,
            download_error="下载内容为空",
        )
        _mark_task_blocked(task["id"], ErrorCode.DOWNLOAD_FAILED.value, "下载内容为空")
        raise BlockedError(
            "附件内容为空",
            code=ErrorCode.DOWNLOAD_FAILED.value,
            instance_id=instance_id,
            attachment_id=attachment_id,
        )

    digest = hashlib.sha256(content).hexdigest()
    if upstream_checksum and upstream_checksum.lower() != digest:
        _update_attachment(
            document_id,
            download_status=DownloadStatus.FAILED.value,
            file_size=len(content),
            download_error="SHA-256 校验不一致",
        )
        _mark_task_blocked(
            task["id"], ErrorCode.CHECKSUM_MISMATCH.value, "附件 SHA-256 校验不一致"
        )
        raise BlockedError(
            "附件 SHA-256 校验不一致",
            code=ErrorCode.CHECKSUM_MISMATCH.value,
            expected=upstream_checksum,
            actual=digest,
        )

    target = local_attachment_path(instance_id, attachment_id, file_name)
    temp_path = target.with_name(target.name + ".part")
    temp_path.write_bytes(content)
    os.replace(temp_path, target)

    _update_attachment(
        document_id,
        download_status=DownloadStatus.SUCCESS.value,
        file_path=_relative_to_base(target),
        sha256=digest,
        file_size=len(content),
    )
    primary = _refresh_primary(task["id"])

    return {
        "document_id": document_id,
        "instance_id": instance_id,
        "approval_code": instance_id,
        "upstream_attachment_id": str(attachment_id),
        "file_name": local["file_name"],
        "file_type": local["file_type"],
        "sort_order": int(local.get("sort_order") or 0),
        "file_path": _relative_to_base(target),
        "sha256": digest,
        "file_size": len(content),
        "checksum_verified": bool(upstream_checksum),
        "download_status": DownloadStatus.SUCCESS.value,
        "is_primary": bool(primary and primary["id"] == document_id),
    }


def select_primary_attachment(attachments: list[dict]) -> dict | None:
    """按 sort_order 选择第一个受支持且下载成功的非空附件。"""
    ordered = sorted(
        attachments,
        key=lambda item: (int(item.get("sort_order") or 0), int(item.get("id") or 0)),
    )
    for item in ordered:
        name = item.get("file_name") or ""
        if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if item.get("download_status") != DownloadStatus.SUCCESS.value:
            continue
        if not int(item.get("file_size") or 0):
            continue
        return item
    return None


def mark_primary(task_id: int, document_id: int | None) -> None:
    with transaction() as conn:
        conn.execute(
            "UPDATE approval_attachments SET is_primary = 0 WHERE task_id = ?",
            (task_id,),
        )
        if document_id is not None:
            conn.execute(
                """
                UPDATE approval_attachments
                   SET is_primary = 1, updated_at = ?
                 WHERE id = ? AND task_id = ?
                """,
                (_now(), document_id, task_id),
            )
