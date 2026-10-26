"""条款标题识别与分段。"""

from __future__ import annotations

import re
from collections import OrderedDict

from app.services.parser.text_document import TextDocument

SECTION_KEYS = [
    "payment",
    "delivery",
    "acceptance",
    "breach",
    "confidentiality",
    "data",
    "intellectual_property",
    "dispute_resolution",
]

SECTION_ALIASES: "OrderedDict[str, tuple[str, ...]]" = OrderedDict(
    [
        ("payment", ("付款", "支付", "价款", "结算", "费用")),
        ("delivery", ("交付", "交货", "运输", "履行")),
        ("acceptance", ("验收",)),
        ("breach", ("违约", "赔偿", "责任")),
        ("confidentiality", ("保密", "秘密")),
        ("data", ("数据", "个人信息", "隐私")),
        ("intellectual_property", ("知识产权", "著作权", "专利", "商标")),
        ("dispute_resolution", ("争议", "管辖", "仲裁", "诉讼")),
    ]
)

HEADING_RE = re.compile(
    r"^(?:第[一二三四五六七八九十百零〇\d]+条|[一二三四五六七八九十]+、|\d+[.、．])\s*(.*)$"
)


def _match_key(title: str) -> str | None:
    for key, aliases in SECTION_ALIASES.items():
        if any(alias in title for alias in aliases):
            return key
    return None


def _iter_lines(text: str):
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        yield offset, line
        offset += len(raw_line)


def segment_sections(document: TextDocument) -> dict[str, dict]:
    """识别“第X条 / 一、 / 1.”等标题，返回 key -> {raw_text, position}。"""
    text = document.text
    lines = list(_iter_lines(text))

    headings: list[tuple[int, int, str, str]] = []  # start, end, title, key
    for index, (offset, line) in enumerate(lines):
        match = HEADING_RE.match(line.strip())
        if not match:
            continue
        title = match.group(1).strip()
        key = _match_key(title)
        if key is None:
            continue
        headings.append((offset, offset + len(line), title, key))

    sections: dict[str, dict] = {}
    for index, (start, end, title, key) in enumerate(headings):
        if key in sections:
            continue
        next_start = headings[index + 1][0] if index + 1 < len(headings) else len(text)
        raw_text = text[start:next_start].strip()
        sections[key] = {
            "title": title or key,
            "raw_text": raw_text,
            "position": document.position(start, end),
            "status": "found",
        }

    # 没有标题时退化为按关键词找行，尽量保住条款抽取。
    for key, aliases in SECTION_ALIASES.items():
        if key in sections:
            continue
        for offset, line in lines:
            if any(alias in line for alias in aliases):
                sections[key] = {
                    "title": line.strip()[:40],
                    "raw_text": line.strip(),
                    "position": document.position(offset, offset + len(line)),
                    "status": "found",
                }
                break

    for key in SECTION_KEYS:
        sections.setdefault(
            key,
            {
                "title": None,
                "raw_text": None,
                "position": {"type": "document"},
                "status": "missing",
            },
        )
    return sections
