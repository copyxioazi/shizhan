from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "local" / "src"))

from kb_sft_data.config import DataConfig  # noqa: E402
from kb_sft_data.corpus import build_corpus, copy_seed_files  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    cfg = DataConfig.load()
    cfg.ensure_dirs()
    docs_dir = cfg.path("corpus_dir") / "docs"
    if not docs_dir.exists() or not any(docs_dir.glob("*.md")):
        raise SystemExit("no synthetic docs; run 02_generate_docs.py first")
    copy_seed_files(cfg)
    build_corpus(cfg, force=args.force)


if __name__ == "__main__":
    main()
