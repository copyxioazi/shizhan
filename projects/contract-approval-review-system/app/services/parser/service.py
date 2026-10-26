"""parse_contract_document 编排。"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from app.db import transaction
from app.errors import BlockedError, NotFoundError, ToolError
from app.services.attachments import resolve_stored_path
from app.services.parser.docx_parser import parse_docx
from app.services.parser.fields import (
    BASIC_FIELDS,
    CLAUSE_FIELDS,
    extract_basic_info,
    extract_clauses,
)
from app.services.parser.ocr import ocr_image
from app.services.parser.pdf_parser import parse_pdf
from app.services.parser.text_document import (
    TextDocument,
    TextSegment,
    build_document,
)
from app.status import ErrorCode, ParseStatus, Stage, TaskStatus

PARSER_VERSION = "1.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def _load_attachment(document_id: int) -> dict:
    with transaction() as conn:
        row = conn.execute(
            "SELECT * FROM approval_attachments WHERE id = ?", (document_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(
                f"附件不存在: {document_id}",
                code="ATTACHMENT_NOT_FOUND",
                document_id=document_id,
            )
        task = conn.execute(
            "SELECT * FROM approval_tasks WHERE id = ?", (row["task_id"],)
        ).fetchone()
    attachment = _row_to_dict(row)
    attachment["task"] = _row_to_dict(task) if task is not None else None
    return attachment


def _parse_file(path: Path, file_type: str) -> TextDocument:
    suffix = path.suffix.lower()
    kind = (file_type or "").lower() or suffix.lstrip(".")
    if kind == "pdf" or suffix == ".pdf":
        return parse_pdf(path)
    if kind in {"docx", "doc"} or suffix == ".docx":
        return parse_docx(path)
    if kind in {"png", "jpg", "jpeg"} or suffix in {".png", ".jpg", ".jpeg"}:
        rows = ocr_image(path)
        segments = [
            TextSegment(
                text=row["text"],
                source="ocr",
                page=row.get("page", 1),
                line=row.get("line"),
                bbox=row.get("bbox"),
            )
            for row in rows
        ]
        warnings = [] if rows else ["OCR 未识别到任何文字"]
        return build_document(
            segments, page_count=1, ocr_used=True, warnings=warnings
        )
    raise ToolError(f"不支持的附件类型: {file_type or suffix}", code="PARSE_FAILED")


def _serialize(fields: dict) -> dict:
    return {key: value.to_dict() for key, value in fields.items()}


def _missing_summary(fields: dict, keys: list[str]) -> list[str]:
    return [
        key
        for key in keys
        if getattr(fields.get(key), "status", "missing") != "found"
    ]


def _mark_task(
    task_id: int,
    *,
    status: str,
    stage: str,
    error_code: str | None = None,
    error: str | None = None,
) -> None:
    with transaction() as conn:
        conn.execute(
            """
            UPDATE approval_tasks
               SET task_status = ?, stage = ?, last_error_code = ?, last_error = ?,
                   updated_at = ?
             WHERE id = ?
            """,
            (status, stage, error_code, error, _now(), task_id),
        )


def _save_parse(
    *,
    task_id: int,
    source_attachment_id: int,
    sha256: str | None,
    parsed: TextDocument | None,
    basic_info: dict | None,
    clause_info: dict | None,
    parse_status: str,
    parse_error: str | None,
    warnings: list[str],
    duration_ms: int,
) -> None:
    now = _now()
    basic_json = json.dumps(basic_info, ensure_ascii=False) if basic_info else None
    clause_json = json.dumps(clause_info, ensure_ascii=False) if clause_info else None
    warnings_json = json.dumps(warnings, ensure_ascii=False)
    text_content = parsed.text if parsed is not None else None
    segments_json = (
        json.dumps([segment.to_dict() for segment in parsed.segments], ensure_ascii=False)
        if parsed is not None
        else None
    )
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO contract_parses
                (task_id, basic_info_json, clause_info_json, parse_status,
                 parse_error, created_at, source_attachment_id, sha256,
                 page_count, ocr_used, text_length, warnings_json,
                 parser_version, duration_ms, updated_at, text_content,
                 segments_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                basic_info_json = excluded.basic_info_json,
                clause_info_json = excluded.clause_info_json,
                parse_status = excluded.parse_status,
                parse_error = excluded.parse_error,
                source_attachment_id = excluded.source_attachment_id,
                sha256 = excluded.sha256,
                page_count = excluded.page_count,
                ocr_used = excluded.ocr_used,
                text_length = excluded.text_length,
                warnings_json = excluded.warnings_json,
                parser_version = excluded.parser_version,
                duration_ms = excluded.duration_ms,
                updated_at = excluded.updated_at,
                text_content = excluded.text_content,
                segments_json = excluded.segments_json
            """,
            (
                task_id,
                basic_json,
                clause_json,
                parse_status,
                parse_error,
                now,
                source_attachment_id,
                sha256,
                parsed.page_count if parsed is not None else None,
                1 if parsed is not None and parsed.ocr_used else 0,
                len(parsed.text) if parsed is not None else 0,
                warnings_json,
                PARSER_VERSION,
                duration_ms,
                now,
                text_content,
                segments_json,
            ),
        )


def parse_document(document_id: int) -> dict:
    """读取附件、按类型解析、抽取字段/条款、写入 contract_parses。"""
    started = time.perf_counter()
    attachment = _load_attachment(document_id)
    task = attachment.get("task")
    if task is None:
        raise NotFoundError(
            f"附件对应的审批任务不存在: {document_id}",
            code="TASK_NOT_FOUND",
            document_id=document_id,
        )

    path = resolve_stored_path(attachment.get("file_path"))
    if (
        path is None
        or not path.is_file()
        or attachment.get("download_status") != "success"
    ):
        message = "附件尚未成功下载，无法解析"
        _mark_task(
            task["id"],
            status=TaskStatus.BLOCKED.value,
            stage=Stage.PARSE.value,
            error_code=ErrorCode.MISSING_ATTACHMENT.value,
            error=message,
        )
        raise BlockedError(
            message,
            code=ErrorCode.MISSING_ATTACHMENT.value,
            document_id=document_id,
        )

    try:
        document = _parse_file(path, attachment.get("file_type") or "")
    except ToolError as exc:
        _mark_task(
            task["id"],
            status=TaskStatus.BLOCKED.value,
            stage=Stage.PARSE.value,
            error_code=exc.code,
            error=exc.message,
        )
        raise BlockedError(
            exc.message,
            code=exc.code,
            document_id=document_id,
        ) from exc
    except Exception as exc:  # noqa: BLE001 - 解析失败统一阻塞
        _mark_task(
            task["id"],
            status=TaskStatus.BLOCKED.value,
            stage=Stage.PARSE.value,
            error_code=ErrorCode.PARSE_FAILED.value,
            error=str(exc),
        )
        raise BlockedError(
            f"文档解析失败：{exc}",
            code=ErrorCode.PARSE_FAILED.value,
            document_id=document_id,
        ) from exc

    duration_ms = int((time.perf_counter() - started) * 1000)

    if not document.text.strip():
        message = "文档没有可用的文字内容"
        _save_parse(
            task_id=task["id"],
            source_attachment_id=document_id,
            sha256=attachment.get("sha256"),
            parsed=document,
            basic_info=None,
            clause_info=None,
            parse_status=ParseStatus.FAILED.value,
            parse_error=message,
            warnings=document.warnings,
            duration_ms=duration_ms,
        )
        _mark_task(
            task["id"],
            status=TaskStatus.BLOCKED.value,
            stage=Stage.PARSE.value,
            error_code=ErrorCode.EMPTY_DOCUMENT.value,
            error=message,
        )
        raise BlockedError(
            message,
            code=ErrorCode.EMPTY_DOCUMENT.value,
            document_id=document_id,
        )

    try:
        basic_info = extract_basic_info(document)
        clause_info = extract_clauses(document)
    except Exception as exc:  # noqa: BLE001
        _save_parse(
            task_id=task["id"],
            source_attachment_id=document_id,
            sha256=attachment.get("sha256"),
            parsed=document,
            basic_info=None,
            clause_info=None,
            parse_status=ParseStatus.FAILED.value,
            parse_error=str(exc),
            warnings=document.warnings,
            duration_ms=duration_ms,
        )
        _mark_task(
            task["id"],
            status=TaskStatus.BLOCKED.value,
            stage=Stage.PARSE.value,
            error_code=ErrorCode.PARSE_FAILED.value,
            error=str(exc),
        )
        raise BlockedError(
            f"字段抽取失败：{exc}",
            code=ErrorCode.PARSE_FAILED.value,
            document_id=document_id,
        ) from exc

    basic_serialized = _serialize(basic_info)
    clause_serialized = _serialize(clause_info)
    missing_basic = _missing_summary(basic_info, BASIC_FIELDS)
    missing_clauses = _missing_summary(clause_info, CLAUSE_FIELDS)

    warnings = list(document.warnings)
    if missing_basic:
        warnings.append("缺失基本信息：" + "、".join(missing_basic))
    if missing_clauses:
        warnings.append("缺失条款：" + "、".join(missing_clauses))

    parse_status = (
        ParseStatus.SUCCESS.value
        if not missing_basic and not missing_clauses and not document.warnings
        else ParseStatus.PARTIAL.value
    )

    _save_parse(
        task_id=task["id"],
        source_attachment_id=document_id,
        sha256=attachment.get("sha256"),
        parsed=document,
        basic_info=basic_serialized,
        clause_info=clause_serialized,
        parse_status=parse_status,
        parse_error=None,
        warnings=warnings,
        duration_ms=duration_ms,
    )
    _mark_task(
        task["id"],
        status=TaskStatus.REVIEWING.value,
        stage=Stage.REVIEW.value,
        error_code=None,
        error=None,
    )

    return {
        "document_id": document_id,
        "case_id": task["id"],
        "parse_status": parse_status,
        "parse_error": None,
        "basic_info": basic_serialized,
        "clause_info": clause_serialized,
        "page_count": document.page_count,
        "ocr_used": document.ocr_used,
        "text_length": len(document.text),
        "warnings": warnings,
        "missing_fields": missing_basic,
        "missing_clauses": missing_clauses,
        "duration_ms": duration_ms,
        "parser_version": PARSER_VERSION,
    }
