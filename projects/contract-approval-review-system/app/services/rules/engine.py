"""规则执行、证据与风险汇总。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from app.db import transaction
from app.errors import NotFoundError, ToolError
from app.services.logs import log_task
from app.services.parser.text_document import TextDocument, TextSegment
from app.services.rules.matchers import (
    MatchContext,
    Rule,
    RuleConfigError,
    get_matcher,
)
from app.status import RISK_ORDER, Stage, TaskStatus

RISK_LABELS = {"high": "高风险", "medium": "中风险", "low": "低风险"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def aggregate_risk(hits: list[dict]) -> str:
    """high > medium > low；无命中返回 low。"""
    levels = {str(hit.get("risk_level")) for hit in hits}
    if "high" in levels:
        return "high"
    if "medium" in levels:
        return "medium"
    return "low"


def _sort_hits(hits: list[dict]) -> list[dict]:
    return sorted(
        hits,
        key=lambda hit: (
            -RISK_ORDER.get(str(hit.get("risk_level")), 0),
            int(hit.get("sort_order") or 0),
            str(hit.get("rule_code") or ""),
        ),
    )


def build_focus_points(hits: list[dict], parse_status: str = "success") -> list[str]:
    """每条命中一个关注点，最多 8 条；partial 时加人工核对提示。"""
    points: list[str] = []
    if parse_status == "partial":
        points.append("解析完整度不足，请人工核对缺失字段。")

    if not hits:
        points.append("未发现规则命中的重大风险，仍建议人工复核合同实质条款。")
        return points[:8]

    for hit in _sort_hits(hits):
        name = hit.get("rule_name") or hit.get("rule_code") or "未知规则"
        suggestion = hit.get("suggestion_text") or ""
        level = RISK_LABELS.get(str(hit.get("risk_level")), "风险")
        points.append(f"{name}（{level}）：{suggestion}".strip("："))
        if len(points) >= 8:
            break
    return points[:8]


def _load_document(parse_row: sqlite3.Row) -> TextDocument:
    warnings = json.loads(parse_row["warnings_json"] or "[]")
    if parse_row["text_content"] is None:
        return TextDocument(
            text="", page_count=parse_row["page_count"] or 0, warnings=warnings
        )
    segments_payload = json.loads(parse_row["segments_json"] or "[]")
    return TextDocument(
        text=parse_row["text_content"] or "",
        segments=[TextSegment.from_dict(item) for item in segments_payload],
        page_count=parse_row["page_count"] or 0,
        ocr_used=bool(parse_row["ocr_used"]),
        warnings=warnings,
    )


def _rule_from_row(row: sqlite3.Row) -> Rule:
    return Rule(
        id=row["id"],
        rule_code=row["rule_code"],
        rule_name=row["rule_name"],
        risk_level=row["risk_level"],
        rule_status=row["rule_status"],
        match_mode=row["match_mode"],
        match_text=row["match_text"],
        suggestion_text=row["suggestion_text"],
        category=row["category"],
        sort_order=row["sort_order"] or 0,
    )


def _save_hits(task_id: int, hits: list[dict]) -> None:
    with transaction() as conn:
        conn.execute("DELETE FROM rule_hits WHERE task_id = ?", (task_id,))
        now = _now()
        for hit in hits:
            conn.execute(
                """
                INSERT INTO rule_hits
                    (task_id, rule_id, evidence_text, evidence_position,
                     hit_status, created_at, rule_name_snapshot,
                     risk_level_snapshot, suggestion_snapshot, matched_value)
                VALUES (?, ?, ?, ?, 'hit', ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    hit["rule_id"],
                    hit["evidence_text"],
                    json.dumps(hit["position"], ensure_ascii=False),
                    now,
                    hit["rule_name"],
                    hit["risk_level"],
                    hit["suggestion_text"],
                    hit.get("matched_value"),
                ),
            )


def run_rules(case_id: int) -> dict:
    """读取解析结果和启用规则，生成 rule_hits 与审查结论。"""
    with transaction() as conn:
        task_row = conn.execute(
            "SELECT * FROM approval_tasks WHERE id = ?", (case_id,)
        ).fetchone()
        if task_row is None:
            raise NotFoundError(
                f"审批任务不存在: {case_id}", code="TASK_NOT_FOUND", case_id=case_id
            )
        parse_row = conn.execute(
            "SELECT * FROM contract_parses WHERE task_id = ?", (case_id,)
        ).fetchone()
        rule_rows = conn.execute(
            """
            SELECT * FROM review_rules
             WHERE rule_status = 'enabled'
             ORDER BY sort_order ASC, id ASC
            """
        ).fetchall()

    if parse_row is None or parse_row["parse_status"] == "failed":
        raise ToolError(
            "合同尚未成功解析，无法执行规则审查",
            code="PARSE_NOT_READY",
            case_id=case_id,
        )

    document = _load_document(parse_row)
    if not document.text:
        raise ToolError(
            "解析结果缺少原文，无法执行规则审查",
            code="PARSE_NOT_READY",
            case_id=case_id,
        )

    basic_info = json.loads(parse_row["basic_info_json"] or "{}")
    clause_info = json.loads(parse_row["clause_info_json"] or "{}")
    context = MatchContext(
        document=document,
        basic_info=basic_info,
        clause_info=clause_info,
    )
    parse_status = parse_row["parse_status"]

    hits: list[dict] = []
    skipped: list[dict] = []
    for rule_row in rule_rows:
        rule = _rule_from_row(rule_row)
        try:
            matcher = get_matcher(rule.match_mode)
            match = matcher.match(rule, context)
        except (RuleConfigError, ToolError) as exc:
            skipped.append({"rule_code": rule.rule_code, "reason": str(exc)})
            log_task(
                case_id,
                "WARN",
                "RULE_SKIPPED",
                f"规则 {rule.rule_code} 配置非法，已跳过：{exc}",
                stage=Stage.REVIEW.value,
                detail={"rule_code": rule.rule_code, "match_mode": rule.match_mode},
            )
            continue
        except Exception as exc:  # noqa: BLE001 - 单条规则不能拖垮整单
            skipped.append({"rule_code": rule.rule_code, "reason": str(exc)})
            log_task(
                case_id,
                "WARN",
                "RULE_SKIPPED",
                f"规则 {rule.rule_code} 执行异常，已跳过：{exc}",
                stage=Stage.REVIEW.value,
                detail={"rule_code": rule.rule_code},
            )
            continue

        if match is None:
            continue
        hits.append(
            {
                "rule_id": rule.id,
                "rule_code": rule.rule_code,
                "rule_name": rule.rule_name,
                "risk_level": rule.risk_level,
                "category": rule.category,
                "suggestion_text": rule.suggestion_text,
                "sort_order": rule.sort_order,
                "evidence_text": match.evidence_text,
                "position": match.position,
                "matched_value": match.matched_value,
            }
        )

    hits = _sort_hits(hits)
    overall_risk = aggregate_risk(hits)
    focus_points = build_focus_points(hits, parse_status)

    _save_hits(case_id, hits)
    with transaction() as conn:
        conn.execute(
            """
            UPDATE approval_tasks
               SET task_status = ?, stage = ?, last_error_code = NULL,
                   last_error = NULL, updated_at = ?
             WHERE id = ?
            """,
            (
                TaskStatus.REVIEWING.value,
                Stage.REVIEW.value,
                _now(),
                case_id,
            ),
        )

    log_task(
        case_id,
        "INFO",
        "RULES_EXECUTED",
        f"规则执行完成：命中 {len(hits)} 条，整体风险 {overall_risk}",
        stage=Stage.REVIEW.value,
        detail={
            "hit_count": len(hits),
            "skipped": len(skipped),
            "overall_risk": overall_risk,
        },
    )

    return {
        "case_id": case_id,
        "overall_risk_level": overall_risk,
        "hit_count": len(hits),
        "hits": hits,
        "focus_points": focus_points,
        "parse_status": parse_status,
        "skipped_rules": skipped,
    }
