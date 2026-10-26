from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any, Iterable

import yaml

from .chunking import clean_text, quality_flag, split_markdown
from .config import DataConfig, project_path
from .io_utils import ensure_dir, read_json, sha256_text, write_json, write_jsonl

FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    match = FRONT_RE.match(text)
    if not match:
        return {}, text
    meta = yaml.safe_load(match.group(1)) or {}
    return meta, text[match.end() :]


def _attach(chunk: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    chunk.update(
        {
            "file_title": meta.get("file_title", ""),
            "item_name": meta.get("item_name", ""),
            "product_model": meta.get("product_model", ""),
            "brand": meta.get("brand", ""),
            "doc_type": meta.get("doc_type", ""),
            "source": meta.get("source", "local"),
            "url": meta.get("url", ""),
            "version": meta.get("version", ""),
            "effective_date": meta.get("effective_date", ""),
            "split": meta.get("split", ""),
            "source_type": meta.get("source_type", "synthetic"),
            "sha256": sha256_text(chunk.get("content", "")),
        }
    )
    return chunk


def _seed_meta() -> dict[str, Any]:
    return {
        "doc_id": "hak180",
        "file_title": "hak180产品安全手册",
        "item_name": "兄弟(Brother)HAK180烫金机",
        "product_model": "HAK180",
        "brand": "Brother",
        "doc_type": "safety_manual",
        "url": "http://www.95105369.com/Web/Manuals.aspx",
        "version": "",
        "effective_date": "",
        "split": "train",
        "source_type": "real",
        "source": "local",
    }


def load_hak180_seed(split_path: str | Path, md_path: str | Path | None = None) -> list[dict[str, Any]]:
    split_path = Path(split_path)
    meta = _seed_meta()
    chunks: list[dict[str, Any]] = []
    if split_path.exists():
        rows = read_json(split_path)
        for idx, row in enumerate(rows):
            content = clean_text(str(row.get("content", "")))
            title = str(row.get("title", "")).strip()
            if title and not content.startswith(title):
                content = f"{title}\n\n{content}"
            if not content:
                continue
            chunks.append(
                {
                    "chunk_id": f"hak180:c{idx:03d}",
                    "doc_id": "hak180",
                    "title": title,
                    "display_title": re.sub(r"^#+\s*", "", title),
                    "section_path": [re.sub(r"^#+\s*", "", title)] if title else [],
                    "part": int(row.get("part", 0) or 0),
                    "content": content,
                    "char_len": len(content),
                    "is_table": "<table" in content.lower() or content.count("|") >= 3,
                    "quality": quality_flag(content),
                }
            )
            chunks[-1] = _attach(chunks[-1], meta)
            chunks[-1]["file_title"] = str(row.get("file_title", meta["file_title"]))
        return chunks
    if md_path and Path(md_path).exists():
        text = Path(md_path).read_text(encoding="utf-8")
        for chunk in split_markdown(text, doc_id="hak180"):
            chunks.append(_attach(chunk, meta))
        return chunks
    raise SystemExit(f"HAK180 seed not found: {split_path} or {md_path}")


def load_pdf(path: str | Path, meta: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        import fitz  # PyMuPDF
    except ImportError:  # pragma: no cover
        print(f"[warn] PyMuPDF missing; skipping {path}. pip install pymupdf")
        return []
    doc = fitz.open(str(path))
    pages = [page.get_text("text").strip() for page in doc]
    text = "\n\n".join(p for p in pages if p)
    if not text.strip():
        raise SystemExit(
            f"{path} has no text layer. Convert it with MinerU first, then place the md at "
            f"data/raw/multimeter/multimeter.md"
        )
    body = f"# {meta['file_title']}\n\n" + text
    chunks = []
    for chunk in split_markdown(body, doc_id=meta["doc_id"]):
        chunks.append(_attach(chunk, meta))
    return chunks


def load_synthetic_docs(docs_dir: str | Path) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for path in sorted(Path(docs_dir).glob("*.md")):
        text = path.read_text(encoding="utf-8")
        meta, body = parse_front_matter(text)
        if not meta.get("doc_id"):
            continue
        for chunk in split_markdown(body, doc_id=meta["doc_id"]):
            chunks.append(_attach(chunk, meta))
    return chunks


def multimeter_meta() -> dict[str, Any]:
    return {
        "doc_id": "rs12",
        "file_title": "万用表 RS-12 使用说明",
        "item_name": "RS-12 数字万用表",
        "product_model": "RS-12",
        "brand": "MeasurePro",
        "doc_type": "user_manual",
        "url": "https://kb.example.com/docs/rs12-manual",
        "version": "",
        "effective_date": "",
        "split": "test",
        "source_type": "real",
        "source": "local",
    }


def _dedupe_ids(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, int] = {}
    for chunk in chunks:
        cid = chunk["chunk_id"]
        if cid in seen:
            seen[cid] += 1
            chunk["chunk_id"] = f"{cid}-{seen[cid]}"
        else:
            seen[cid] = 0
    return chunks


def build_corpus(config: DataConfig, force: bool = False) -> list[dict[str, Any]]:
    config.ensure_dirs()
    corpus_dir = config.path("corpus_dir")
    out_path = corpus_dir / "corpus.jsonl"
    docs_dir = corpus_dir / "docs"

    seed_cfg = config.corpus.get("seed", {})
    chunks: list[dict[str, Any]] = []
    chunks.extend(load_hak180_seed(seed_cfg.get("hak180_split", ""), seed_cfg.get("hak180_md")))
    chunks.extend(load_synthetic_docs(docs_dir))

    pdf_path = project_path(seed_cfg.get("multimeter_pdf", ""))
    md_fallback = config.path("raw_dir") / "multimeter" / "multimeter.md"
    if md_fallback.exists():
        text = md_fallback.read_text(encoding="utf-8")
        for chunk in split_markdown(text, doc_id="rs12"):
            chunks.append(_attach(chunk, multimeter_meta()))
    elif pdf_path.exists():
        chunks.extend(load_pdf(pdf_path, multimeter_meta()))
    else:
        print(f"[warn] multimeter PDF not found: {pdf_path}; continuing without it")

    chunks = _dedupe_ids(chunks)
    min_chars = int(config.corpus.get("min_chunk_chars", 30))
    kept = [c for c in chunks if c.get("quality") != "low" and c.get("char_len", 0) >= min_chars]
    kept.sort(key=lambda c: (c["split"], c["doc_id"], c["chunk_id"]))

    write_jsonl(out_path, kept)
    docs: dict[str, dict[str, Any]] = {}
    for chunk in kept:
        docs.setdefault(
            chunk["doc_id"],
            {
                "doc_id": chunk["doc_id"],
                "file_title": chunk.get("file_title", ""),
                "item_name": chunk.get("item_name", ""),
                "product_model": chunk.get("product_model", ""),
                "brand": chunk.get("brand", ""),
                "doc_type": chunk.get("doc_type", ""),
                "url": chunk.get("url", ""),
                "version": chunk.get("version", ""),
                "effective_date": chunk.get("effective_date", ""),
                "split": chunk.get("split", ""),
                "source_type": chunk.get("source_type", ""),
            },
        )
    by_split: dict[str, int] = {}
    for chunk in kept:
        by_split[chunk["split"]] = by_split.get(chunk["split"], 0) + 1
    meta = {
        "total_chunks": len(kept),
        "by_split": by_split,
        "docs": docs,
        "corpus_sha256": sha256_text("\n".join(c["chunk_id"] + c["sha256"] for c in kept)),
    }
    write_json(corpus_dir / "corpus_meta.json", meta)
    print(f"corpus: {len(kept)} chunks, splits={by_split}, docs={len(docs)} -> {out_path}")
    return kept


def load_corpus(path: str | Path) -> list[dict[str, Any]]:
    from .io_utils import read_jsonl

    return list(read_jsonl(path))


def copy_seed_files(config: DataConfig) -> None:
    """Copy seed inputs into data/raw for reproducibility; never modify the source."""
    raw = config.path("raw_dir")
    ensure_dir(raw / "hak180")
    seed = config.corpus.get("seed", {})
    for key, name in (("hak180_split", "split.json"), ("hak180_md", "hak180_new.md")):
        src = project_path(seed.get(key, ""))
        if src.exists():
            shutil.copy2(src, raw / "hak180" / name)
