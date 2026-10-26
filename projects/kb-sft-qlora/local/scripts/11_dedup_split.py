from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "local" / "src"))

from kb_sft_data.config import DataConfig  # noqa: E402
from kb_sft_data.dedup import deduplicate  # noqa: E402
from kb_sft_data.io_utils import read_json, read_jsonl, write_json  # noqa: E402
from kb_sft_data.splitter import leakage_report, write_splits  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    cfg = DataConfig.load()
    pool = cfg.path("splits_dir") / "_pool.jsonl"
    if not pool.exists():
        raise SystemExit(f"missing {pool}; run 10_build_dataset.py")
    samples = list(read_jsonl(pool))
    kept, stats = deduplicate(samples)
    corpus_meta_path = cfg.path("corpus_dir") / "corpus_meta.json"
    corpus_meta = read_json(corpus_meta_path) if corpus_meta_path.exists() else {}
    manifest = write_splits(
        kept,
        cfg.path("splits_dir"),
        gold_per_split=100,
        seed=cfg.seed,
        corpus_sha256=corpus_meta.get("corpus_sha256", ""),
        corpus_meta=corpus_meta,
    )
    leak = leakage_report(kept)
    write_json(cfg.path("splits_dir") / "dedup_report.json", {"dedup": stats, "leakage": leak})
    print(json.dumps({"dedup": stats, "counts": manifest["counts"], "leakage": leak["ok"]},
                     ensure_ascii=False, indent=2))
    if not leak["ok"]:
        print(f"[error] leakage: chunks={leak['chunk_overlap'][:10]} docs={leak['doc_overlap']}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
