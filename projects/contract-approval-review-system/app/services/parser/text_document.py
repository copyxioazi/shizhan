"""统一文本表示与位置映射。"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field


@dataclass
class TextSegment:
    text: str
    source: str  # pdf | docx | ocr
    start: int = 0
    page: int | None = None
    paragraph_index: int | None = None
    line: int | None = None
    bbox: list[float] | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "TextSegment":
        return cls(
            text=str(payload.get("text") or ""),
            source=str(payload.get("source") or ""),
            start=int(payload.get("start") or 0),
            page=payload.get("page"),
            paragraph_index=payload.get("paragraph_index"),
            line=payload.get("line"),
            bbox=payload.get("bbox"),
        )


@dataclass
class TextDocument:
    text: str = ""
    segments: list[TextSegment] = field(default_factory=list)
    page_count: int = 0
    ocr_used: bool = False
    warnings: list[str] = field(default_factory=list)

    def position(self, start: int, end: int) -> dict:
        """把全文偏移映射为 pdf/docx/ocr 的结构化位置。"""
        if not self.segments or not self.text:
            return {"type": "document"}

        start = max(0, min(int(start), len(self.text)))
        end = max(start, min(int(end), len(self.text)))

        segment = self._segment_at(start)
        if segment is None:
            return {"type": "document"}

        local_start = max(0, start - segment.start)
        local_end = min(len(segment.text), max(local_start, end - segment.start))

        if segment.source == "pdf":
            return {
                "type": "pdf",
                "page": segment.page or 1,
                "char_start": local_start,
                "char_end": local_end,
            }
        if segment.source == "docx":
            return {
                "type": "docx",
                "paragraph_index": segment.paragraph_index or 0,
                "char_start": local_start,
                "char_end": local_end,
            }
        if segment.source == "ocr":
            return {
                "type": "ocr",
                "page": segment.page or 1,
                "line": segment.line or 1,
                "char_start": local_start,
                "char_end": local_end,
                "bbox": segment.bbox,
            }
        return {"type": "document"}

    def _segment_at(self, offset: int) -> TextSegment | None:
        previous = None
        for segment in self.segments:
            if not segment.text:
                continue
            if segment.start <= offset < segment.start + len(segment.text):
                return segment
            if segment.start > offset:
                return previous or segment
            previous = segment
        return previous

    def snippet(self, start: int, end: int, window: int = 60) -> str:
        """命中前后各 window 字，压缩空白并加省略号。"""
        left = max(0, start - window)
        right = min(len(self.text), end + window)
        text = re.sub(r"\s+", " ", self.text[left:right]).strip()
        prefix = "…" if left > 0 else ""
        suffix = "…" if right < len(self.text) else ""
        return f"{prefix}{text}{suffix}"

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "segments": [segment.to_dict() for segment in self.segments],
            "page_count": self.page_count,
            "ocr_used": self.ocr_used,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "TextDocument":
        return cls(
            text=str(payload.get("text") or ""),
            segments=[
                TextSegment.from_dict(item)
                for item in payload.get("segments") or []
            ],
            page_count=int(payload.get("page_count") or 0),
            ocr_used=bool(payload.get("ocr_used")),
            warnings=[str(item) for item in payload.get("warnings") or []],
        )


def build_document(
    segments: list[TextSegment],
    *,
    separator: str = "\n",
    page_count: int = 0,
    ocr_used: bool = False,
    warnings: list[str] | None = None,
) -> TextDocument:
    """把若干段按顺序拼接，并回填段的全局起始偏移。"""
    parts: list[str] = []
    cursor = 0
    for index, segment in enumerate(segments):
        segment.text = segment.text or ""
        segment.start = cursor
        parts.append(segment.text)
        cursor += len(segment.text)
        if index != len(segments) - 1:
            parts.append(separator)
            cursor += len(separator)
    return TextDocument(
        text="".join(parts),
        segments=segments,
        page_count=page_count,
        ocr_used=ocr_used,
        warnings=list(warnings or []),
    )
