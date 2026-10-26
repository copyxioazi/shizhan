"""6 种 match_mode 的匹配器测试。"""

from __future__ import annotations

import json

import pytest

from app.services.parser.text_document import TextSegment, build_document
from app.services.rules.engine import aggregate_risk, build_focus_points
from app.services.rules.matchers import (
    MatchContext,
    Rule,
    RuleConfigError,
    get_matcher,
)

TEXT = (
    "第一条 付款条款\n"
    "合同签订后支付预付款 60%，剩余款项于验收合格后 90 天内支付。\n"
    "第二条 保密条款\n"
    "双方应对保密信息承担保密义务。\n"
    "第三条 争议解决\n"
    "由乙方所在地人民法院管辖。"
)


def _context() -> MatchContext:
    document = build_document(
        [TextSegment(text=TEXT, source="pdf", page=1)], page_count=1
    )
    return MatchContext(
        document=document,
        basic_info={
            "party_a": {"value": "甲方", "status": "found", "position": {"type": "pdf"}},
            "party_b": {"value": None, "status": "missing", "position": {"type": "document"}},
            "amount": {"value": "1200000", "status": "found", "position": {"type": "pdf"}},
            "currency": {"value": "CNY", "status": "found", "position": {"type": "pdf"}},
        },
        clause_info={},
    )


def _rule(mode: str, match_text, risk_level: str = "medium") -> Rule:
    if not isinstance(match_text, str):
        match_text = json.dumps(match_text, ensure_ascii=False)
    return Rule(
        rule_code="T001",
        rule_name="测试规则",
        risk_level=risk_level,
        rule_status="enabled",
        match_mode=mode,
        match_text=match_text,
        suggestion_text="测试建议",
        sort_order=10,
    )


def test_keyword_matcher() -> None:
    context = _context()
    match = get_matcher("keyword").match(_rule("keyword", "保密"), context)
    assert match is not None
    assert match.position["type"] == "pdf"
    assert "保密" in match.evidence_text

    assert get_matcher("keyword").match(_rule("keyword", "验收标准"), context) is None

    latin = build_document([TextSegment(text="Payment Terms", source="pdf")], page_count=1)
    latin_context = MatchContext(latin, {}, {})
    assert get_matcher("keyword").match(_rule("keyword", "payment"), latin_context)


def test_all_keywords_matcher() -> None:
    context = _context()
    hit = get_matcher("all_keywords").match(
        _rule("all_keywords", ["预付款", "验收"]), context
    )
    assert hit is not None
    assert hit.matched_value == "预付款、验收"
    assert (
        get_matcher("all_keywords").match(
            _rule("all_keywords", ["预付款", "验收标准"]), context
        )
        is None
    )


def test_regex_matcher_and_invalid_regex() -> None:
    context = _context()
    hit = get_matcher("regex").match(
        _rule("regex", r"预付款\s*(\d+)%"), context
    )
    assert hit is not None
    assert hit.matched_value == "预付款 60%"

    with pytest.raises(RuleConfigError):
        get_matcher("regex").match(_rule("regex", "("), context)


def test_absence_matcher() -> None:
    context = _context()
    hit = get_matcher("absence").match(_rule("absence", ["知识产权"]), context)
    assert hit is not None
    assert hit.position == {"type": "document"}
    assert "知识产权" in hit.evidence_text

    assert get_matcher("absence").match(_rule("absence", ["保密"]), context) is None


def test_field_check_matcher() -> None:
    context = _context()
    any_missing = get_matcher("field_check").match(
        _rule("field_check", {"fields": ["party_a", "party_b"], "op": "any_missing"}),
        context,
    )
    assert any_missing is not None
    assert "party_b" in (any_missing.matched_value or "")

    missing_amount = get_matcher("field_check").match(
        _rule("field_check", {"field": "amount", "op": "missing"}), context
    )
    assert missing_amount is None

    equals = get_matcher("field_check").match(
        _rule("field_check", {"field": "currency", "op": "equals", "value": "CNY"}),
        context,
    )
    assert equals is not None

    with pytest.raises(RuleConfigError):
        get_matcher("field_check").match(
            _rule("field_check", "{not-json"), context
        )


def test_numeric_threshold_matcher() -> None:
    context = _context()
    config = {
        "pattern": r"预付款\s*(\d+(?:\.\d+)?)\s*%",
        "group": 1,
        "op": "gt",
        "threshold": 30,
        "unit": "%",
    }
    hit = get_matcher("numeric_threshold").match(
        _rule("numeric_threshold", config), context
    )
    assert hit is not None
    assert hit.matched_value == "60%"

    boundary = dict(config, threshold=60)
    assert (
        get_matcher("numeric_threshold").match(
            _rule("numeric_threshold", boundary), context
        )
        is None
    )

    between = {
        "pattern": r"账期\s*(\d+)\s*天|(\d+)\s*天内支付",
        "group": 1,
        "op": "between",
        "threshold": 1,
        "upper": 30,
    }
    # 用更直接的 pattern 验证 between 的违规区间。
    between["pattern"] = r"(\d+)\s*天内支付"
    hit = get_matcher("numeric_threshold").match(
        _rule("numeric_threshold", between), context
    )
    assert hit is not None

    with pytest.raises(RuleConfigError):
        get_matcher("numeric_threshold").match(
            _rule("numeric_threshold", {"pattern": "([0-9]+", "op": "gt", "threshold": 1}),
            context,
        )


def test_risk_aggregation_and_focus_points() -> None:
    manual = [
        {"rule_name": "高", "rule_code": "R1", "risk_level": "medium", "suggestion_text": "a", "sort_order": 1},
        {"rule_name": "极高", "rule_code": "R2", "risk_level": "high", "suggestion_text": "b", "sort_order": 2},
    ]
    assert aggregate_risk(manual) == "high"
    assert aggregate_risk([manual[0]]) == "medium"
    assert aggregate_risk([]) == "low"

    points = build_focus_points(manual, parse_status="partial")
    assert points[0] == "解析完整度不足，请人工核对缺失字段。"
    assert any("极高" in point for point in points)

    no_hits = build_focus_points([], parse_status="success")
    assert "未发现规则命中的重大风险" in no_hits[0]

    many = [
        {
            "rule_name": f"规则{i}",
            "rule_code": f"R{i}",
            "risk_level": "low",
            "suggestion_text": "建议",
            "sort_order": i,
        }
        for i in range(12)
    ]
    assert len(build_focus_points(many)) == 8


def test_get_matcher_rejects_unknown_mode() -> None:
    from app.errors import ToolError

    with pytest.raises(ToolError):
        get_matcher("unknown")
