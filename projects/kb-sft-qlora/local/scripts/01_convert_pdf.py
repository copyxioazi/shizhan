from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "local" / "src"))

from kb_sft_data.config import DataConfig, project_path  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", default="")
    parser.add_argument("--out", default="")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    cfg = DataConfig.load()
    seed = cfg.corpus.get("seed", {})
    pdf = project_path(args.pdf or seed.get("multimeter_pdf", ""))
    out = Path(args.out) if args.out else cfg.path("raw_dir") / "multimeter" / "multimeter.md"
    if out.exists() and not args.force:
        print(f"exists: {out} (pass --force to reconvert)")
        return
    if not pdf.exists():
        raise SystemExit(f"PDF not found: {pdf}")

    try:
        import fitz
    except ImportError as exc:
        raise SystemExit("pip install pymupdf") from exc

    doc = fitz.open(str(pdf))
    pages = [page.get_text("text").strip() for page in doc]
    text = "\n\n".join(page for page in pages if page)
    if len(text.strip()) < 100:
        raise SystemExit(
            f"{pdf} looks like a scanned PDF (text={len(text)} chars). Convert it with MinerU, "
            f"then save the markdown to {out}."
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("# 万用表 RS-12 使用说明\n\n" + text + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(text)} chars, {len(pages)} pages)")


if __name__ == "__main__":
    main()
