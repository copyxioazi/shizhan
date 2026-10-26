"""DOCX 解析：段落/表格顺序遍历，位置用段落索引。"""

from __future__ import annotations

from pathlib import Path

from app.errors import ToolError
from app.services.parser.text_document import (
    TextDocument,
    TextSegment,
    build_document,
)


def _iter_blocks(document):
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def parse_docx(path: Path) -> TextDocument:
    try:
        from docx import Document
    except ImportError as exc:
        raise ToolError(
            "python-docx 未安装，无法解析 DOCX", code="PARSER_UNAVAILABLE"
        ) from exc

    try:
        document = Document(str(path))
    except Exception as exc:  # noqa: BLE001 - 损坏/加密文档
        raise ToolError(f"DOCX 无法读取：{exc}", code="PARSE_FAILED") from exc

    segments: list[TextSegment] = []
    paragraph_index = 0
    for block in _iter_blocks(document):
        if hasattr(block, "rows") and hasattr(block, "columns"):
            # 表格逐行扁平化，按行记录段落索引。
            for row in block.rows:
                cells = [
                    " ".join(cell.text.split())
                    for cell in row.cells
                    if cell.text.strip()
                ]
                text = " | ".join(cells).strip()
                if text:
                    segments.append(
                        TextSegment(
                            text=text,
                            source="docx",
                            paragraph_index=paragraph_index,
                        )
                    )
                    paragraph_index += 1
            continue

        text = (block.text or "").strip()
        if text:
            segments.append(
                TextSegment(
                    text=text,
                    source="docx",
                    paragraph_index=paragraph_index,
                )
            )
            paragraph_index += 1

    return build_document(segments, page_count=0)
