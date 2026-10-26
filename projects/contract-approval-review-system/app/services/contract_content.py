"""合同解析内容读取：全文、基本信息、条款与命中位置。"""

from __future__ import annotations

import json
import sqlite3

from app.db import transaction
from app.errors import NotFoundError


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def _json(value: str | None, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except ValueError:
        return default


def get_contract_content(case_id: int) -> dict:
    """按本地 case_id 返回解析后的合同内容。"""
    with transaction() as conn:
        task = conn.execute(
            "SELECT * FROM approval_tasks WHERE id = ?", (case_id,)
        ).fetchone()
        if task is None:
            raise NotFoundError(
                f"审批任务不存在: {case_id}", code="TASK_NOT_FOUND", case_id=case_id
            )
        parse = conn.execute(
            "SELECT * FROM contract_parses WHERE task_id = ?", (case_id,)
        ).fetchone()
        attachment = None
        if parse is not None and parse["source_attachment_id"]:
            attachment = conn.execute(
                "SELECT * FROM approval_attachments WHERE id = ?",
                (parse["source_attachment_id"],),
            ).fetchone()
        hit_rows = conn.execute(
            """
            SELECT h.*, r.rule_code, r.category, r.sort_order
              FROM rule_hits h
              JOIN review_rules r ON r.id = h.rule_id
             WHERE h.task_id = ? AND h.hit_status = 'hit'
             ORDER BY r.sort_order ASC, h.id ASC
            """,
            (case_id,),
        ).fetchall()

    if parse is None:
        return {
            "case_id": case_id,
            "approval_code": task["approval_code"],
            "approval_title": task["approval_title"],
            "document_id": None,
            "file_name": None,
            "file_path": None,
            "parse_status": None,
            "parse_error": None,
            "basic_info": {},
            "clause_info": {},
            "text_content": "",
            "segments": [],
            "warnings": [],
            "page_count": None,
            "ocr_used": False,
            "text_length": 0,
            "updated_at": None,
            "hits": [],
        }

    hits = []
    for row in hit_rows:
        hits.append(
            {
                "rule_id": row["rule_id"],
                "rule_code": row["rule_code"],
                "rule_name": row["rule_name_snapshot"],
                "risk_level": row["risk_level_snapshot"],
                "category": row["category"],
                "suggestion_text": row["suggestion_snapshot"],
                "evidence_text": row["evidence_text"],
                "position": _json(row["evidence_position"], {"type": "document"}),
                "matched_value": row["matched_value"],
                "sort_order": row["sort_order"] or 0,
            }
        )

    return {
        "case_id": case_id,
        "approval_code": task["approval_code"],
        "approval_title": task["approval_title"],
        "document_id": parse["source_attachment_id"],
        "file_name": attachment["file_name"] if attachment else None,
        "file_path": attachment["file_path"] if attachment else None,
        "parse_status": parse["parse_status"],
        "parse_error": parse["parse_error"],
        "basic_info": _json(parse["basic_info_json"], {}),
        "clause_info": _json(parse["clause_info_json"], {}),
        "text_content": parse["text_content"] or "",
        "segments": _json(parse["segments_json"], []),
        "warnings": _json(parse["warnings_json"], []),
        "page_count": parse["page_count"],
        "ocr_used": bool(parse["ocr_used"]),
        "text_length": parse["text_length"] or 0,
        "updated_at": parse["updated_at"],
        "hits": hits,
    }
