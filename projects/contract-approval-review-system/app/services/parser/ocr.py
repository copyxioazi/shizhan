"""RapidOCR 懒加载单例与扫描件识别。"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from app.errors import ToolError

_engine: Any | None = None
_engine_lock = threading.Lock()


def get_ocr_engine() -> Any:
    """懒加载 RapidOCR；同一 ONNX session 并发调用需外层加锁。"""
    global _engine
    with _engine_lock:
        if _engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as exc:
                raise ToolError(
                    "RapidOCR 未安装，无法识别扫描件",
                    code="OCR_UNAVAILABLE",
                ) from exc
            _engine = RapidOCR()
        return _engine


def _run_engine(image) -> list[dict]:
    engine = get_ocr_engine()
    # ONNX session 不是并发安全的，识别调用整体串行化。
    with _engine_lock:
        try:
            result, _elapse = engine(image)
        except Exception as exc:  # noqa: BLE001 - 第三方库异常类型不稳定
            raise ToolError(
                f"OCR 识别失败：{exc}", code="OCR_FAILED"
            ) from exc

    rows: list[dict] = []
    for item in result or []:
        if len(item) < 2:
            continue
        box, text = item[0], str(item[1] or "").strip()
        if not text:
            continue
        points = [(float(point[0]), float(point[1])) for point in box]
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        rows.append(
            {
                "text": text,
                "bbox": [min(xs), min(ys), max(xs), max(ys)],
                "top": min(ys),
                "left": min(xs),
            }
        )

    rows.sort(key=lambda row: (round(row["top"] / 8), row["left"]))
    for index, row in enumerate(rows, start=1):
        row["line"] = index
        row.pop("top", None)
        row.pop("left", None)
    return rows


def _load_image(image) -> Any:
    from PIL import Image

    if isinstance(image, (str, Path)):
        with Image.open(image) as handle:
            return handle.convert("RGB").copy()
    return image


def ocr_image(image, page: int = 1) -> list[dict]:
    """返回按版面顺序排列的 OCR 行：text、line、bbox。"""
    rows = _run_engine(_load_image(image))
    for row in rows:
        row["page"] = page
    return rows


def ocr_pdf_pages(path: Path, dpi: int = 200) -> tuple[list[dict], list[str]]:
    """把 PDF 每页渲染为图片后逐页 OCR，单页失败不阻断其他页。"""
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise ToolError(
            "pypdfium2 未安装，无法渲染 PDF 扫描页",
            code="OCR_UNAVAILABLE",
        ) from exc

    rows: list[dict] = []
    warnings: list[str] = []
    document = pdfium.PdfDocument(str(path))
    try:
        for index, page in enumerate(document, start=1):
            try:
                bitmap = page.render(scale=dpi / 72)
                image = bitmap.to_pil().convert("RGB")
                page_rows = ocr_image(image, page=index)
                if not page_rows:
                    warnings.append(f"第 {index} 页未识别到文字")
                rows.extend(page_rows)
            except ToolError:
                raise
            except Exception as exc:  # noqa: BLE001 - 单页失败降级为警告
                warnings.append(f"第 {index} 页 OCR 失败：{exc}")
    finally:
        document.close()
    return rows, warnings


def ocr_pdf(path: Path, dpi: int = 200) -> list[dict]:
    """兼容旧签名的 PDF OCR：返回所有页的行。"""
    rows, _warnings = ocr_pdf_pages(path, dpi)
    return rows
