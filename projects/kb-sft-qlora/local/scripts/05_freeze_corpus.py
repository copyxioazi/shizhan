from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "local" / "src"))

from kb_sft_data.config import DataConfig  # noqa: E402
from kb_sft_data.io_utils import now_iso, sha256_file  # noqa: E402


def main() -> None:
    cfg = DataConfig.load()
    corpus_dir = cfg.path("corpus_dir")
    corpus = corpus_dir / "corpus.jsonl"
    if not corpus.exists():
        raise SystemExit("corpus.jsonl missing; run 03_build_corpus.py")
    docs_dir = corpus_dir / "docs"
    lock = {
        "frozen_at": now_iso(),
        "corpus_sha256": sha256_file(corpus),
        "config_sha256": sha256_file(ROOT / "local" / "configs" / "data.yaml"),
        "docs": {
            str(p.relative_to(corpus_dir)): sha256_file(p)
            for p in sorted(docs_dir.glob("*.md"))
        },
    }
    embeddings = corpus_dir / "embeddings.npz"
    if embeddings.exists():
        lock["embeddings_sha256"] = sha256_file(embeddings)
    out = corpus_dir / "freeze.lock"
    out.write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"frozen -> {out} ({len(lock['docs'])} docs)")


if __name__ == "__main__":
    main()
