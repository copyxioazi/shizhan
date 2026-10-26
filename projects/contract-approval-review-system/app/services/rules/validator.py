"""规则新增/修改时的校验。"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.errors import ToolError
from app.status import RISK_LEVEL_VALUES
from app.services.rules.matchers import MATCHER_MODES

FIELD_CHECK_OPS = {"exists", "missing", "any_missing", "equals", "not_equals", "in"}
NUMERIC_OPS = {"gt", "gte", "lt", "lte", "eq", "between"}


def _fail(message: str, **details: Any) -> None:
    raise ToolError(message, code="INVALID_RULE", **details)


def _json_value(raw: Any, mode: str):
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(str(raw))
    except ValueError:
        _fail(f"{mode} 的 match_text 必须是合法 JSON", match_mode=mode)


def _validate_keywords(raw: Any, mode: str) -> list[str]:
    value = _json_value(raw, mode)
    if not isinstance(value, list) or not value:
        _fail(f"{mode} 需要非空字符串数组", match_mode=mode)
    if not all(isinstance(item, str) and item.strip() for item in value):
        _fail(f"{mode} 的每个关键词都必须是非空字符串", match_mode=mode)
    return [item.strip() for item in value]


def _validate_field_check(raw: Any) -> dict:
    value = _json_value(raw, "field_check")
    if not isinstance(value, dict):
        _fail("field_check 需要 JSON 对象", match_mode="field_check")
    op = value.get("op")
    if op not in FIELD_CHECK_OPS:
        _fail(f"field_check 不支持的 op：{op}", match_mode="field_check")
    fields = value.get("fields")
    field = value.get("field")
    if not fields and not field:
        _fail("field_check 需要 field 或 fields", match_mode="field_check")
    if fields is not None and not isinstance(fields, list):
        _fail("field_check 的 fields 必须是数组", match_mode="field_check")
    return value


def _validate_numeric(raw: Any) -> dict:
    value = _json_value(raw, "numeric_threshold")
    if not isinstance(value, dict):
        _fail("numeric_threshold 需要 JSON 对象", match_mode="numeric_threshold")
    pattern = value.get("pattern")
    if not pattern or not isinstance(pattern, str):
        _fail("numeric_threshold 缺少 pattern", match_mode="numeric_threshold")
    try:
        re.compile(pattern, re.MULTILINE)
    except re.error as exc:
        _fail(f"numeric_threshold 正则非法：{exc}", match_mode="numeric_threshold")
    if value.get("op") not in NUMERIC_OPS:
        _fail(
            f"numeric_threshold 不支持的 op：{value.get('op')}",
            match_mode="numeric_threshold",
        )
    try:
        Decimal(str(value.get("threshold")))
    except (InvalidOperation, TypeError):
        _fail("numeric_threshold 的 threshold 必须是数字", match_mode="numeric_threshold")
    if value.get("op") == "between":
        try:
            Decimal(str(value.get("upper")))
        except (InvalidOperation, TypeError):
            _fail("between 需要数字 upper", match_mode="numeric_threshold")
    return value


def validate_rule(payload: dict[str, Any]) -> dict[str, Any]:
    """校验 risk_level、match_mode、match_text JSON/正则等。"""
    rule_code = str(payload.get("rule_code") or "").strip()
    rule_name = str(payload.get("rule_name") or "").strip()
    suggestion = str(payload.get("suggestion_text") or "").strip()
    risk_level = str(payload.get("risk_level") or "")
    mode = str(payload.get("match_mode") or "")
    raw_match = payload.get("match_text")

    if not rule_code:
        _fail("rule_code 不能为空")
    if not rule_name:
        _fail("rule_name 不能为空")
    if not suggestion:
        _fail("suggestion_text 不能为空")
    if risk_level not in RISK_LEVEL_VALUES:
        _fail(f"非法风险等级：{risk_level}", risk_level=risk_level)
    if mode not in MATCHER_MODES:
        _fail(f"非法匹配模式：{mode}", match_mode=mode)

    if mode in {"keyword", "regex"}:
        if not isinstance(raw_match, str) or not raw_match.strip():
            _fail(f"{mode} 的 match_text 必须是非空字符串", match_mode=mode)
        if mode == "regex":
            try:
                re.compile(raw_match, re.MULTILINE | re.DOTALL)
            except re.error as exc:
                _fail(f"正则表达式非法：{exc}", match_mode=mode)
        match_text = raw_match.strip()
    elif mode in {"all_keywords", "absence"}:
        match_text = json.dumps(
            _validate_keywords(raw_match, mode), ensure_ascii=False
        )
    elif mode == "field_check":
        match_text = json.dumps(_validate_field_check(raw_match), ensure_ascii=False)
    else:
        match_text = json.dumps(_validate_numeric(raw_match), ensure_ascii=False)

    rule_status = str(payload.get("rule_status") or "enabled")
    if rule_status not in {"enabled", "disabled"}:
        _fail(f"非法规则状态：{rule_status}", rule_status=rule_status)

    return {
        "rule_code": rule_code,
        "rule_name": rule_name,
        "risk_level": risk_level,
        "rule_status": rule_status,
        "match_mode": mode,
        "match_text": match_text,
        "suggestion_text": suggestion,
        "category": payload.get("category"),
        "sort_order": int(payload.get("sort_order") or 0),
    }
