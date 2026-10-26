"""6 种 match_mode 的匹配器实现。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from app.errors import ToolError
from app.services.parser.text_document import TextDocument

FIELD_LABELS = {
    "contract_title": "合同标题",
    "contract_no": "合同编号",
    "party_a": "甲方",
    "party_b": "乙方",
    "amount": "合同金额",
    "currency": "币种",
    "effective_date": "生效日期",
    "expiry_date": "到期日期",
}


class RuleConfigError(ValueError):
    """规则 JSON/正则非法，上层应跳过并告警。"""


@dataclass
class Rule:
    rule_code: str
    rule_name: str
    risk_level: str
    rule_status: str
    match_mode: str
    match_text: str
    suggestion_text: str
    id: int | None = None
    category: str | None = None
    sort_order: int = 0


@dataclass
class RuleMatch:
    rule: Rule
    start: int
    end: int
    evidence_text: str
    position: dict
    matched_value: str | None = None


@dataclass
class MatchContext:
    document: TextDocument
    basic_info: dict[str, dict]
    clause_info: dict[str, dict]


class Matcher(Protocol):
    mode: str

    def match(self, rule: Rule, context: MatchContext) -> RuleMatch | None:
        ...


def _json_list(raw: str, mode: str) -> list[str]:
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise RuleConfigError(f"{mode} match_text 不是合法 JSON") from exc
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuleConfigError(f"{mode} match_text 必须是字符串数组")
    return value


def _json_object(raw: str, mode: str) -> dict:
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise RuleConfigError(f"{mode} match_text 不是合法 JSON") from exc
    if not isinstance(value, dict):
        raise RuleConfigError(f"{mode} match_text 必须是 JSON 对象")
    return value


def _first_index(text: str, keyword: str) -> re.Match | None:
    return re.search(re.escape(keyword), text, re.IGNORECASE)


def _make_match(
    rule: Rule,
    context: MatchContext,
    start: int,
    end: int,
    matched_value: str | None = None,
) -> RuleMatch:
    return RuleMatch(
        rule=rule,
        start=start,
        end=end,
        evidence_text=context.document.snippet(start, end),
        position=context.document.position(start, end),
        matched_value=matched_value,
    )


class KeywordMatcher:
    mode = "keyword"

    def match(self, rule: Rule, context: MatchContext) -> RuleMatch | None:
        keyword = rule.match_text.strip()
        if not keyword:
            raise RuleConfigError("keyword 不能为空")
        found = _first_index(context.document.text, keyword)
        if found is None:
            return None
        return _make_match(rule, context, found.start(), found.end(), keyword)


class AllKeywordsMatcher:
    mode = "all_keywords"

    def match(self, rule: Rule, context: MatchContext) -> RuleMatch | None:
        keywords = _json_list(rule.match_text, self.mode)
        if not keywords:
            raise RuleConfigError("all_keywords 至少需要一个关键词")
        ranges: list[tuple[int, int]] = []
        for keyword in keywords:
            found = _first_index(context.document.text, keyword)
            if found is None:
                return None
            ranges.append((found.start(), found.end()))
        start = min(item[0] for item in ranges)
        end = max(item[1] for item in ranges)
        return _make_match(rule, context, start, end, "、".join(keywords))


class RegexMatcher:
    mode = "regex"

    def match(self, rule: Rule, context: MatchContext) -> RuleMatch | None:
        try:
            pattern = re.compile(rule.match_text, re.MULTILINE | re.DOTALL)
        except re.error as exc:
            raise RuleConfigError(f"正则表达式非法：{exc}") from exc
        found = pattern.search(context.document.text)
        if found is None:
            return None
        return _make_match(rule, context, found.start(), found.end(), found.group(0))


class AbsenceMatcher:
    mode = "absence"

    def match(self, rule: Rule, context: MatchContext) -> RuleMatch | None:
        keywords = _json_list(rule.match_text, self.mode)
        if not keywords:
            raise RuleConfigError("absence 至少需要一个关键词")
        if any(_first_index(context.document.text, keyword) for keyword in keywords):
            return None
        evidence = "未检出相关表述：" + "、".join(keywords)
        return RuleMatch(
            rule=rule,
            start=0,
            end=0,
            evidence_text=evidence,
            position={"type": "document"},
            matched_value=None,
        )


class FieldCheckMatcher:
    mode = "field_check"

    def match(self, rule: Rule, context: MatchContext) -> RuleMatch | None:
        config = _json_object(rule.match_text, self.mode)
        op = str(config.get("op") or "")
        fields_value = config.get("fields")
        if isinstance(fields_value, list):
            fields = [str(item) for item in fields_value]
        elif config.get("field"):
            fields = [str(config["field"])]
        else:
            fields = []
        if not fields:
            raise RuleConfigError("field_check 缺少 field/fields")

        def info(field: str) -> dict:
            value = context.basic_info.get(field) or {}
            return value if isinstance(value, dict) else {}

        def label(field: str) -> str:
            return FIELD_LABELS.get(field, field)

        if op == "any_missing":
            missing = [field for field in fields if info(field).get("status") != "found"]
            if not missing:
                return None
            return RuleMatch(
                rule=rule,
                start=0,
                end=0,
                evidence_text="字段缺失：" + "、".join(label(item) for item in missing),
                position={"type": "document"},
                matched_value="、".join(missing),
            )

        field = fields[0]
        field_info = info(field)
        status = field_info.get("status")
        value = field_info.get("value")
        position = field_info.get("position") or {"type": "document"}

        if op == "missing":
            if status == "found":
                return None
            evidence = f"字段缺失：{label(field)}"
        elif op == "exists":
            if status != "found":
                return None
            evidence = f"字段存在：{label(field)} = {value}"
        elif op == "equals":
            if status != "found" or str(value) != str(config.get("value")):
                return None
            evidence = f"字段匹配：{label(field)} = {value}"
        elif op == "not_equals":
            if status != "found" or str(value) == str(config.get("value")):
                return None
            evidence = f"字段不等于预期：{label(field)} = {value}"
        elif op == "in":
            expected = config.get("values") or config.get("value") or []
            if not isinstance(expected, list):
                expected = [expected]
            if status != "found" or value not in expected:
                return None
            evidence = f"字段匹配：{label(field)} = {value}"
        else:
            raise RuleConfigError(f"不支持的 field_check 操作：{op}")

        return RuleMatch(
            rule=rule,
            start=0,
            end=0,
            evidence_text=evidence,
            position=position,
            matched_value=str(value) if value is not None else None,
        )


class NumericThresholdMatcher:
    mode = "numeric_threshold"

    def match(self, rule: Rule, context: MatchContext) -> RuleMatch | None:
        config = _json_object(rule.match_text, self.mode)
        pattern_text = str(config.get("pattern") or "")
        if not pattern_text:
            raise RuleConfigError("numeric_threshold 缺少 pattern")
        try:
            pattern = re.compile(pattern_text, re.MULTILINE)
        except re.error as exc:
            raise RuleConfigError(f"正则表达式非法：{exc}") from exc

        group = int(config.get("group") or 1)
        op = str(config.get("op") or "")
        unit = str(config.get("unit") or "")
        try:
            threshold = Decimal(str(config.get("threshold")))
        except (InvalidOperation, TypeError) as exc:
            raise RuleConfigError("threshold 不是合法数字") from exc
        upper = config.get("upper")
        try:
            upper_value = Decimal(str(upper)) if upper is not None else None
        except InvalidOperation as exc:
            raise RuleConfigError("upper 不是合法数字") from exc

        for found in pattern.finditer(context.document.text):
            try:
                raw_value = found.group(group)
            except IndexError as exc:
                raise RuleConfigError(f"正则没有第 {group} 个捕获组") from exc
            if raw_value is None:
                continue
            try:
                value = Decimal(str(raw_value).replace(",", "").strip())
            except InvalidOperation:
                continue

            violated = False
            if op == "gt":
                violated = value > threshold
            elif op == "gte":
                violated = value >= threshold
            elif op == "lt":
                violated = value < threshold
            elif op == "lte":
                violated = value <= threshold
            elif op == "eq":
                violated = value == threshold
            elif op == "between":
                if upper_value is None:
                    raise RuleConfigError("between 缺少 upper")
                violated = value < threshold or value > upper_value
            else:
                raise RuleConfigError(f"不支持的 numeric_threshold 操作：{op}")

            if violated:
                return _make_match(
                    rule,
                    context,
                    found.start(),
                    found.end(),
                    f"{value}{unit}".strip(),
                )
        return None


MATCHER_MODES = (
    "keyword",
    "all_keywords",
    "regex",
    "absence",
    "field_check",
    "numeric_threshold",
)

MATCHER_REGISTRY: dict[str, type[Matcher]] = {
    "keyword": KeywordMatcher,
    "all_keywords": AllKeywordsMatcher,
    "regex": RegexMatcher,
    "absence": AbsenceMatcher,
    "field_check": FieldCheckMatcher,
    "numeric_threshold": NumericThresholdMatcher,
}


def get_matcher(mode: str) -> Matcher:
    matcher_class = MATCHER_REGISTRY.get(mode)
    if matcher_class is None:
        raise ToolError(
            f"不支持的规则匹配模式：{mode}",
            code="INVALID_RULE_MODE",
            mode=mode,
        )
    return matcher_class()
