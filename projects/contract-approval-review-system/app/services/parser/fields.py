"""基本信息与 8 类条款抽取。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.services.parser.sections import SECTION_KEYS, segment_sections
from app.services.parser.text_document import TextDocument


@dataclass
class ParsedField:
    value: str | None
    raw_text: str | None
    position: dict
    status: str  # found | missing | invalid

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "raw_text": self.raw_text,
            "position": self.position,
            "status": self.status,
        }


BASIC_FIELDS = [
    "contract_title",
    "contract_no",
    "party_a",
    "party_b",
    "amount",
    "currency",
    "effective_date",
    "expiry_date",
]

CLAUSE_FIELDS = [
    "payment",
    "delivery",
    "acceptance",
    "breach",
    "confidentiality",
    "data",
    "intellectual_property",
    "dispute_resolution",
]

DATE_PATTERN = (
    r"([0-9]{4}\s*年\s*[0-9]{1,2}\s*月\s*[0-9]{1,2}\s*日"
    r"|[0-9]{4}[-/][0-9]{1,2}[-/][0-9]{1,2})"
)

CURRENCY_VALUES = {
    "人民币": "CNY",
    "RMB": "CNY",
    "CNY": "CNY",
    "美元": "USD",
    "USD": "USD",
    "欧元": "EUR",
    "EUR": "EUR",
}


def _line_at(text: str, offset: int) -> str:
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    if end == -1:
        end = len(text)
    return text[start:end].strip()


def _missing() -> ParsedField:
    return ParsedField(None, None, {"type": "document"}, "missing")


def _field_from_match(
    document: TextDocument,
    match: re.Match,
    value: str | None = None,
    status: str = "found",
) -> ParsedField:
    raw_text = _line_at(document.text, match.start())
    group_value = match.group(1) if match.lastindex and match.lastindex >= 1 else None
    resolved = value if value is not None else (group_value or "").strip() or None
    return ParsedField(
        value=resolved,
        raw_text=raw_text or None,
        position=document.position(match.start(), match.end()),
        status=status if resolved else "invalid",
    )


def _label_without_value(document: TextDocument, pattern: str) -> bool:
    return re.search(pattern, document.text, re.MULTILINE) is not None


def _normalize_amount(value: str, unit: str | None) -> str | None:
    cleaned = value.replace(",", "").replace("，", "").strip()
    if not cleaned:
        return None
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    if unit == "万元":
        amount *= Decimal(10000)
    normalized = format(amount.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def _normalize_date(value: str) -> str | None:
    numbers = re.findall(r"\d+", value)
    if len(numbers) != 3:
        return None
    year, month, day = (int(item) for item in numbers)
    if not (1900 <= year <= 2200 and 1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def extract_basic_info(document: TextDocument) -> dict[str, ParsedField]:
    text = document.text
    result: dict[str, ParsedField] = {}

    title_match = re.search(
        r"^(?![第\d一二三四五六七八九十]+[条、.．])\s*([^\n]{2,40}?(?:合同|协议))\s*$",
        text,
        re.MULTILINE,
    )
    result["contract_title"] = (
        _field_from_match(document, title_match) if title_match else _missing()
    )

    contract_no_match = re.search(
        r"(?:合同编号|协议编号|合同号|协议号)\s*[：:]\s*([A-Za-z0-9][A-Za-z0-9\-_/]*)",
        text,
    )
    result["contract_no"] = (
        _field_from_match(document, contract_no_match)
        if contract_no_match
        else _missing()
    )

    party_patterns = {
        "party_a": r"(?:甲方|买方|采购方|委托方)\s*(?:（[^）\n]{0,12}）|\([^)\n]{0,12}\))?\s*[：:]\s*([^\n，。；]{2,60})",
        "party_b": r"(?:乙方|卖方|供方|服务方|受托方)\s*(?:（[^）\n]{0,12}）|\([^)\n]{0,12}\))?\s*[：:]\s*([^\n，。；]{2,60})",
    }
    for key, pattern in party_patterns.items():
        match = re.search(pattern, text)
        if match:
            result[key] = ParsedField(
                value=match.group(1).strip() or None,
                raw_text=_line_at(text, match.start()),
                position=document.position(match.start(), match.end()),
                status="found" if match.group(1).strip() else "invalid",
            )
        else:
            result[key] = _missing()

    amount_match = re.search(
        r"(?:合同金额|合同总价|合同价款|总金额|价款)\s*[：:]\s*"
        r"(?:人民币|RMB|CNY|美元|USD|欧元|EUR|¥|￥)?\s*"
        r"([0-9][0-9,，]*(?:\.[0-9]+)?)\s*(万元|元)?",
        text,
    )
    if amount_match:
        normalized = _normalize_amount(
            amount_match.group(1), amount_match.group(2)
        )
        result["amount"] = _field_from_match(
            document,
            amount_match,
            value=normalized,
            status="found" if normalized else "invalid",
        )
    else:
        result["amount"] = _missing()

    currency_match = re.search(
        r"(人民币|RMB|CNY|美元|USD|欧元|EUR)", text, re.IGNORECASE
    )
    if currency_match:
        result["currency"] = ParsedField(
            value=CURRENCY_VALUES.get(currency_match.group(1).upper())
            or CURRENCY_VALUES.get(currency_match.group(1)),
            raw_text=_line_at(text, currency_match.start()),
            position=document.position(currency_match.start(), currency_match.end()),
            status="found",
        )
    else:
        result["currency"] = _missing()

    date_patterns = {
        "effective_date": (
            r"(?:生效日期|合同生效日|开始日期|起始日期)\s*[：:]?\s*" + DATE_PATTERN
        ),
        "expiry_date": (
            r"(?:到期日期|终止日期|届满日期|有效期至|合同期限至)\s*[：:]?\s*"
            + DATE_PATTERN
        ),
    }
    for key, pattern in date_patterns.items():
        match = re.search(pattern, text)
        if match:
            normalized = _normalize_date(match.group(1))
            result[key] = ParsedField(
                value=normalized,
                raw_text=_line_at(text, match.start()),
                position=document.position(match.start(), match.end()),
                status="found" if normalized else "invalid",
            )
        else:
            label = "生效|开始|起始" if key == "effective_date" else "到期|终止|届满|有效期"
            result[key] = (
                ParsedField(None, None, {"type": "document"}, "invalid")
                if _label_without_value(document, rf"(?:{label})日期?\s*[：:]")
                else _missing()
            )

    for key in BASIC_FIELDS:
        result.setdefault(key, _missing())
    return result


def extract_clauses(document: TextDocument) -> dict[str, ParsedField]:
    sections = segment_sections(document)
    result: dict[str, ParsedField] = {}
    for key in CLAUSE_FIELDS:
        section = sections.get(key) or {}
        status = section.get("status") or "missing"
        if status == "found" and section.get("raw_text"):
            result[key] = ParsedField(
                value=section.get("title"),
                raw_text=section.get("raw_text"),
                position=section.get("position") or {"type": "document"},
                status="found",
            )
        else:
            result[key] = _missing()
    for key in SECTION_KEYS:
        result.setdefault(key, _missing())
    return result
