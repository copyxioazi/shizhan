"""PDF/DOCX/OCR 解析测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings
from app.errors import ToolError
from app.services.parser.docx_parser import parse_docx
from app.services.parser.fields import (
    BASIC_FIELDS,
    CLAUSE_FIELDS,
    extract_basic_info,
    extract_clauses,
)
from app.services.parser.ocr import ocr_image
from app.services.parser.pdf_parser import parse_pdf
from app.services.parser.text_document import TextSegment, build_document


def _sample(name: str) -> Path:
    path = settings.sample_dir / name
    if not path.is_file():
        pytest.skip(f"示例文件不存在：{path}")
    return path


def test_pdf_fields_and_positions() -> None:
    document = parse_pdf(_sample("apv_2026_001_purchase.pdf"))
    assert len(document.text) > 100
    assert document.page_count >= 1
    assert document.ocr_used is False

    basic = extract_basic_info(document)
    for key in BASIC_FIELDS:
        assert basic[key].status == "found", key
    assert basic["contract_no"].value == "CG-2026-001"
    assert basic["amount"].value == "1200000"
    assert basic["currency"].value == "CNY"
    assert basic["effective_date"].value == "2026-03-01"
    assert basic["expiry_date"].value == "2027-02-28"
    assert basic["contract_no"].position["type"] == "pdf"
    assert basic["contract_no"].position["page"] >= 1

    clauses = extract_clauses(document)
    assert all(clauses[key].status == "found" for key in CLAUSE_FIELDS)


def test_docx_fields_and_partial_clause() -> None:
    document = parse_docx(_sample("apv_2026_002_service.docx"))
    basic = extract_basic_info(document)
    assert basic["contract_no"].value == "FW-2026-002"
    assert basic["contract_no"].position["type"] == "docx"
    assert basic["contract_no"].position["paragraph_index"] >= 0

    clauses = extract_clauses(document)
    assert clauses["payment"].status == "found"
    assert clauses["confidentiality"].status == "missing"


@pytest.mark.ocr
def test_scan_png_ocr() -> None:
    path = _sample("apv_2026_003_scan.png")
    rows = ocr_image(path)
    assert rows, "OCR 未识别到文字"
    document = build_document(
        [
            TextSegment(
                text=row["text"],
                source="ocr",
                page=row.get("page", 1),
                line=row.get("line"),
                bbox=row.get("bbox"),
            )
            for row in rows
        ],
        page_count=1,
        ocr_used=True,
    )
    basic = extract_basic_info(document)
    assert basic["contract_no"].status == "missing"
    assert basic["amount"].value == "50000"
    assert basic["party_a"].position["type"] == "ocr"
    clauses = extract_clauses(document)
    assert all(clauses[key].status == "found" for key in CLAUSE_FIELDS)


def test_damaged_files_raise_tool_error(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_text("not a real pdf", encoding="utf-8")
    with pytest.raises(ToolError):
        parse_pdf(broken)

    broken_docx = tmp_path / "broken.docx"
    broken_docx.write_text("not a real docx", encoding="utf-8")
    with pytest.raises(ToolError):
        parse_docx(broken_docx)
