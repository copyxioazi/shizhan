from __future__ import annotations

import re
from typing import Any

SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", ".", "!", "?", ";", " "]
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９％", "0123456789%")
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = IMAGE_RE.sub(lambda m: f"[图片说明：{m.group(1).strip() or '图片'}]", text)
    text = text.translate(FULLWIDTH_DIGITS)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def quality_flag(text: str) -> str:
    if "�" in text:
        return "low"
    if not text:
        return "empty"
    allowed = 0
    for ch in text:
        code = ord(ch)
        if (
            "一" <= ch <= "鿿"
            or 32 <= code < 127
            or ch in "，。！？；：、“”‘’（）【】《》…—·%|/\\-+*#·　"
            or ch.isspace()
        ):
            allowed += 1
    return "low" if allowed / max(len(text), 1) < 0.82 else "ok"


def _iter_sections(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    sections: list[dict[str, Any]] = []
    stack: list[str] = []
    title = ""
    display_title = ""
    body: list[str] = []
    in_code = False

    def flush() -> None:
        nonlocal body, title, display_title
        if title or any(line.strip() for line in body):
            sections.append(
                {
                    "title": title,
                    "display_title": display_title,
                    "section_path": list(stack),
                    "body": "\n".join(body).strip(),
                }
            )
        body = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
        match = None if in_code else HEADING_RE.match(stripped)
        if match:
            flush()
            level = len(match.group(1))
            display_title = match.group(2).strip()
            title = stripped
            stack = stack[: level - 1] + [display_title]
            continue
        body.append(line)
    flush()
    return [s for s in sections if s["body"] or s["title"]]


def _units(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？；.!?;])\s*|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def _hard_split(unit: str, size: int, overlap: int) -> list[str]:
    step = max(1, size - overlap)
    return [unit[i : i + size] for i in range(0, len(unit), step)]


def _pack_units(units: list[str], size: int, overlap: int) -> list[str]:
    normalized: list[str] = []
    for unit in units:
        normalized.extend(_hard_split(unit, size, overlap) if len(unit) > size else [unit])

    chunks: list[str] = []
    current = ""
    for unit in normalized:
        if not current:
            current = unit
            continue
        joiner = "\n" if current.endswith(("。", "！", "？", "；", ".", "!", "?", ";")) else ""
        if len(current) + len(joiner) + len(unit) <= size:
            current += joiner + unit
        else:
            chunks.append(current)
            tail = ""
            if overlap > 0 and len(current) > overlap:
                tail = current[-overlap:]
                boundary = re.search(r"[。！？；.!?;]", tail)
                if boundary:
                    tail = tail[boundary.end() :]
            current = (tail + ("\n" if tail else "") + unit).strip()
    if current:
        chunks.append(current)
    return chunks


def split_markdown(
    text: str,
    *,
    doc_id: str,
    chunk_size: int = 250,
    overlap: int = 50,
    min_chars: int = 30,
) -> list[dict[str, Any]]:
    text = clean_text(text)
    out: list[dict[str, Any]] = []
    for section_idx, section in enumerate(_iter_sections(text)):
        body = section["body"]
        if not body:
            continue
        is_table = "<table" in body.lower() or body.count("|") >= 3
        if is_table or len(body) <= chunk_size:
            parts = [body]
        else:
            parts = _pack_units(_units(body), chunk_size, overlap)
        for part_idx, part in enumerate(parts):
            part = part.strip()
            if not part:
                continue
            title = section["title"]
            content = part if not title or part.startswith(title) else f"{title}\n\n{part}"
            if len(content) < min_chars:
                continue
            out.append(
                {
                    "chunk_id": f"{doc_id}:s{section_idx:02d}:p{part_idx}",
                    "doc_id": doc_id,
                    "title": title,
                    "display_title": section["display_title"],
                    "section_path": section["section_path"],
                    "part": part_idx,
                    "content": content,
                    "char_len": len(content),
                    "is_table": is_table,
                    "quality": quality_flag(content),
                }
            )
    return out
