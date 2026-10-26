"""LLM 可选润色与回退测试。"""

from __future__ import annotations

from app.config import settings
from app.services.llm import polish_review
from app.services.review import build_review


def test_disabled_llm_returns_template() -> None:
    result = polish_review("摘要", ["关注点"], [])
    assert result["summary_text"] == "摘要"
    assert result["focus_points"] == ["关注点"]
    assert result["llm_enhanced"] is False


def test_invalid_llm_endpoint_falls_back() -> None:
    original = (
        settings.llm_enabled,
        settings.llm_base_url,
        settings.llm_model,
        settings.llm_timeout_seconds,
    )
    object.__setattr__(settings, "llm_enabled", True)
    object.__setattr__(settings, "llm_base_url", "http://127.0.0.1:9")
    object.__setattr__(settings, "llm_model", "test-model")
    object.__setattr__(settings, "llm_timeout_seconds", 1)
    try:
        result = polish_review("原摘要", ["原关注点"], [])
        assert result["summary_text"] == "原摘要"
        assert result["focus_points"] == ["原关注点"]
        assert result["llm_enhanced"] is False
    finally:
        object.__setattr__(settings, "llm_enabled", original[0])
        object.__setattr__(settings, "llm_base_url", original[1])
        object.__setattr__(settings, "llm_model", original[2])
        object.__setattr__(settings, "llm_timeout_seconds", original[3])


def test_build_review_uses_rules_without_llm() -> None:
    hits = [
        {
            "rule_code": "R001",
            "rule_name": "预付款比例过高",
            "risk_level": "high",
            "suggestion_text": "建议降低预付款比例。",
            "sort_order": 10,
        }
    ]
    built = build_review(hits, parse_status="partial")
    assert built["overall_risk_level"] == "high"
    assert built["focus_points"][0] == "解析完整度不足，请人工核对缺失字段。"
    assert "高风险" in built["summary_text"]
    assert "合同审查结论" in built["comment_text"]
    assert built["llm_enhanced"] is False
