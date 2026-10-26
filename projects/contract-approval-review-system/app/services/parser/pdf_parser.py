"""PDF 文本层解析与无文本层 OCR 回退。"""

from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.errors import ToolError
from app.services.parser.ocr import ocr_pdf_pages
from app.services.parser.text_document import (
    TextDocument,
    TextSegment,
    build_document,
)


def parse_pdf(path: Path) -> TextDocument:
    """pdfplumber 逐页提取；文本过少时用 pypdfium2 渲染后 OCR。"""
    try:
        import pdfplumber
    except ImportError as exc:
        raise ToolError(
            "pdfplumber 未安装，无法解析 PDF", code="PARSER_UNAVAILABLE"
        ) from exc

    segments: list[TextSegment] = []
    warnings: list[str] = []
    page_count = 0

    try:
        with pdfplumber.open(str(path)) as pdf:
            page_count = len(pdf.pages)
            for index, page in enumerate(pdf.pages, start=1):
                try:
                    text = page.extract_text() or ""
                except Exception as exc:  # noqa: BLE001 - 单页异常降级
                    text = ""
                    warnings.append(f"第 {index} 页文本层提取失败：{exc}")
                text = text.strip()
                if text:
                    segments.append(
                        TextSegment(text=text, source="pdf", page=index)
                    )
                elif not warnings:
                    warnings.append(f"第 {index} 页无文本层")
    except Exception as exc:  # noqa: BLE001 - 损坏/加密 PDF
        raise ToolError(f"PDF 无法读取：{exc}", code="PARSE_FAILED") from exc

    total_chars = sum(len(segment.text) for segment in segments)
    if total_chars < settings.ocr_text_min_chars:
        rows, ocr_warnings = ocr_pdf_pages(path)
        ocr_segments = [
            TextSegment(
                text=row["text"],
                source="ocr",
                page=row.get("page", 1),
                line=row.get("line"),
                bbox=row.get("bbox"),
            )
            for row in rows
        ]
        return build_document(
            ocr_segments,
            page_count=page_count,
            ocr_used=True,
            warnings=[*warnings, *ocr_warnings],
        )

    return build_document(segments, page_count=page_count, warnings=warnings)
