"""审查摘要、关注点与结果持久化。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from app.db import transaction
from app.errors import NotFoundError, ToolError
from app.status import RISK_LEVEL_VALUES
from app.services.llm import polish_review


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def build_review(hits: list[dict], parse_status: str = "success") -> dict:
    """根据命中结果生成总风险、中文摘要、关注点和评论文本。"""
    from app.services.rules.engine import aggregate_risk, build_focus_points

    overall = aggregate_risk(hits)
    focus_points = build_focus_points(hits, parse_status)
    counts = {"high": 0, "medium": 0, "low": 0}
    for hit in hits:
        level = hit.get("risk_level")
        if level in counts:
            counts[level] += 1

    if hits:
        summary = (
            f"本次审查共命中 {len(hits)} 条风险：高风险 {counts['high']} 条、"
            f"中风险 {counts['medium']} 条、低风险 {counts['low']} 条；"
            f"整体风险等级为{_risk_cn(overall)}。"
        )
    else:
        summary = "本次审查未命中规则风险，整体风险等级为低风险，仍建议人工复核合同实质条款。"

    comment_lines = [f"【合同审查结论】整体风险：{_risk_cn(overall)}", summary]
    if focus_points:
        comment_lines.append("重点关注：")
        comment_lines.extend(f"{index}. {point}" for index, point in enumerate(focus_points, 1))
    comment_text = "\n".join(comment_lines)

    try:
        polished = polish_review(summary, focus_points, hits)
    except Exception:  # noqa: BLE001 - LLM 永远不能阻塞主流程
        polished = {
            "summary_text": summary,
            "focus_points": focus_points,
            "llm_enhanced": False,
        }
    return {
        "overall_risk_level": overall,
        "summary_text": polished["summary_text"],
        "focus_points": polished["focus_points"],
        "comment_text": comment_text,
        "llm_enhanced": bool(polished.get("llm_enhanced")),
    }


def _risk_cn(level: str) -> str:
    return {"high": "高风险", "medium": "中风险", "low": "低风险"}.get(level, level)


def save_review(case_id: int, review: dict) -> dict:
    """upsert review_results，返回 review_id。"""
    overall = str(review.get("overall_risk_level") or "").lower()
    if overall not in RISK_LEVEL_VALUES:
        raise ToolError(
            f"非法风险等级: {overall}", code="INVALID_RISK_LEVEL",
            overall_risk_level=overall,
        )
    summary_text = str(review.get("summary_text") or "").strip()
    comment_text = str(review.get("comment_text") or "").strip()
    if not summary_text or not comment_text:
        raise ToolError(
            "审查摘要和评论内容不能为空", code="EMPTY_REVIEW_TEXT", case_id=case_id
        )

    focus_points = review.get("focus_points") or []
    if isinstance(focus_points, str):
        try:
            focus_points = json.loads(focus_points)
        except ValueError as exc:
            raise ToolError(
                "focus_points_json 不是合法 JSON", code="INVALID_FOCUS_POINTS"
            ) from exc
    if not isinstance(focus_points, list) or not all(
        isinstance(item, str) for item in focus_points
    ):
        raise ToolError(
            "focus_points_json 必须是字符串数组", code="INVALID_FOCUS_POINTS"
        )
    focus_points_json = json.dumps(focus_points, ensure_ascii=False)

    now = _now()
    with transaction() as conn:
        task = conn.execute(
            "SELECT id FROM approval_tasks WHERE id = ?", (case_id,)
        ).fetchone()
        if task is None:
            raise NotFoundError(
                f"审批任务不存在: {case_id}", code="TASK_NOT_FOUND", case_id=case_id
            )
        row = conn.execute(
            "SELECT id FROM review_results WHERE task_id = ?", (case_id,)
        ).fetchone()
        if row is None:
            cursor = conn.execute(
                """
                INSERT INTO review_results
                    (task_id, overall_risk_level, summary_text, focus_points_json,
                     comment_text, created_at, updated_at, llm_enhanced)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    overall,
                    summary_text,
                    focus_points_json,
                    comment_text,
                    now,
                    now,
                    1 if review.get("llm_enhanced") else 0,
                ),
            )
            review_id = cursor.lastrowid
            created = True
        else:
            review_id = row["id"]
            conn.execute(
                """
                UPDATE review_results
                   SET overall_risk_level = ?, summary_text = ?,
                       focus_points_json = ?, comment_text = ?,
                       updated_at = ?, llm_enhanced = ?
                 WHERE id = ?
                """,
                (
                    overall,
                    summary_text,
                    focus_points_json,
                    comment_text,
                    now,
                    1 if review.get("llm_enhanced") else 0,
                    review_id,
                ),
            )
            created = False

    return {
        "review_id": review_id,
        "case_id": case_id,
        "overall_risk_level": overall,
        "saved_at": now,
        "created": created,
    }


def get_review(review_id: int) -> dict:
    with transaction() as conn:
        row = conn.execute(
            "SELECT * FROM review_results WHERE id = ?", (review_id,)
        ).fetchone()
    if row is None:
        raise NotFoundError(
            f"审查结果不存在: {review_id}", code="REVIEW_NOT_FOUND",
            review_id=review_id,
        )
    item = _row_to_dict(row)
    item["focus_points"] = json.loads(item.pop("focus_points_json") or "[]")
    return item
