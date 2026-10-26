"""管理端 JSON 接口（规则维护）。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from app.db import transaction
from app.errors import NotFoundError, ToolError
from app.services.rules.validator import validate_rule

router = APIRouter(prefix="/api/admin", tags=["admin"])


class RulePayload(BaseModel):
    rule_code: str
    rule_name: str
    risk_level: str
    rule_status: str = "enabled"
    match_mode: str
    match_text: str | list[str] | dict
    suggestion_text: str
    category: str | None = None
    sort_order: int = 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def _get_rule(conn: sqlite3.Connection, rule_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM review_rules WHERE id = ?", (rule_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError(
            f"规则不存在: {rule_id}", code="RULE_NOT_FOUND", rule_id=rule_id
        )
    return _row_to_dict(row)


@router.get("/rules")
def list_rules() -> dict:
    with transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM review_rules ORDER BY sort_order ASC, id ASC"
        ).fetchall()
    return {"success": True, "data": [_row_to_dict(row) for row in rows]}


@router.post("/rules", status_code=201)
def create_rule(payload: RulePayload) -> dict:
    data = validate_rule(payload.model_dump())
    now = _now()
    try:
        with transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO review_rules
                    (rule_code, rule_name, risk_level, rule_status, match_mode,
                     match_text, suggestion_text, updated_at, category, created_at,
                     sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["rule_code"],
                    data["rule_name"],
                    data["risk_level"],
                    data["rule_status"],
                    data["match_mode"],
                    data["match_text"],
                    data["suggestion_text"],
                    now,
                    data.get("category"),
                    now,
                    data["sort_order"],
                ),
            )
            rule = _get_rule(conn, cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise ToolError(
            f"规则编码已存在：{data['rule_code']}",
            code="DUPLICATE_RULE",
            status_code=409,
            rule_code=data["rule_code"],
        ) from exc
    return {"success": True, "data": rule}


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, payload: RulePayload) -> dict:
    data = validate_rule(payload.model_dump())
    try:
        with transaction() as conn:
            _get_rule(conn, rule_id)
            conn.execute(
                """
                UPDATE review_rules
                   SET rule_code = ?, rule_name = ?, risk_level = ?,
                       rule_status = ?, match_mode = ?, match_text = ?,
                       suggestion_text = ?, updated_at = ?, category = ?,
                       sort_order = ?
                 WHERE id = ?
                """,
                (
                    data["rule_code"],
                    data["rule_name"],
                    data["risk_level"],
                    data["rule_status"],
                    data["match_mode"],
                    data["match_text"],
                    data["suggestion_text"],
                    _now(),
                    data.get("category"),
                    data["sort_order"],
                    rule_id,
                ),
            )
            rule = _get_rule(conn, rule_id)
    except sqlite3.IntegrityError as exc:
        raise ToolError(
            f"规则编码已存在：{data['rule_code']}",
            code="DUPLICATE_RULE",
            status_code=409,
            rule_code=data["rule_code"],
        ) from exc
    return {"success": True, "data": rule}


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int) -> None:
    with transaction() as conn:
        _get_rule(conn, rule_id)
        used = conn.execute(
            "SELECT COUNT(*) FROM rule_hits WHERE rule_id = ?", (rule_id,)
        ).fetchone()[0]
        if used:
            raise ToolError(
                "规则已被历史任务引用，不能硬删除；请改为停用",
                code="RULE_IN_USE",
                status_code=409,
                rule_id=rule_id,
                referenced=used,
            )
        conn.execute("DELETE FROM review_rules WHERE id = ?", (rule_id,))
    return None
