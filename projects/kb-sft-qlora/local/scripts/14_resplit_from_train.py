from __future__ import annotations

import argparse
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "local" / "src"))

from kb_sft_data.config import DataConfig  # noqa: E402
from kb_sft_data.io_utils import read_jsonl, write_json, write_jsonl  # noqa: E402
from kb_sft_data.splitter import leakage_report, stratified_gold  # noqa: E402
from kb_sft_data.verifier import verify_sample  # noqa: E402


def _load_all(splits_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for split in ("train", "dev", "test"):
        path = splits_dir / f"{split}.jsonl"
        if not path.exists():
            continue
        rows.extend(read_jsonl(path))
    seen: set[str] = set()
    unique: list[dict] = []
    for row in rows:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        unique.append(row)
    return unique


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dev-ratio", type=float, default=0.10)
    parser.add_argument("--test-ratio", type=float, default=0.10)
    parser.add_argument("--gold", type=int, default=100)
    args = parser.parse_args()

    cfg = DataConfig.load()
    splits_dir = cfg.path("splits_dir")
    rows = _load_all(splits_dir)
    if not rows:
        raise SystemExit("no train rows to split")

    rng = random.Random(args.seed)
    by_type: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_type[row.get("task_type", "")].append(row)

    train: list[dict] = []
    dev: list[dict] = []
    test: list[dict] = []
    for task_type, items in sorted(by_type.items()):
        items = list(items)
        rng.shuffle(items)
        n = len(items)
        n_dev = max(1, round(n * args.dev_ratio)) if n >= 3 else 0
        n_test = max(1, round(n * args.test_ratio)) if n >= 3 else 0
        if n_dev + n_test >= n:
            n_dev = n_test = 0
        dev.extend(items[:n_dev])
        test.extend(items[n_dev : n_dev + n_test])
        train.extend(items[n_dev + n_test :])

    for group in (train, dev, test):
        rng.shuffle(group)
    for split, group in (("train", train), ("dev", dev), ("test", test)):
        for row in group:
            row["split"] = split
            row.setdefault("metadata", {})["split"] = split

    errors = []
    for row in train + dev + test:
        ok, reasons = verify_sample(row)
        if not ok:
            errors.append({"id": row.get("id"), "reasons": reasons})

    write_jsonl(splits_dir / "train.jsonl", train)
    write_jsonl(splits_dir / "dev.jsonl", dev)
    write_jsonl(splits_dir / "test.jsonl", test)
    write_jsonl(splits_dir / "gold_dev_100.jsonl", stratified_gold(dev, args.gold))
    write_jsonl(splits_dir / "gold_test_100.jsonl", stratified_gold(test, args.gold))

    leak = leakage_report(train + dev + test)
    counts = {
        split: dict(Counter(row.get("task_type", "") for row in group))
        for split, group in (("train", train), ("dev", dev), ("test", test))
    }
    manifest = {
        "split_method": "stratified_random_from_train",
        "seed": args.seed,
        "ratios": {"train": round(1 - args.dev_ratio - args.test_ratio, 2),
                   "dev": args.dev_ratio, "test": args.test_ratio},
        "counts": counts,
        "total": len(train) + len(dev) + len(test),
        "gold_per_split": args.gold,
        "leakage": leak,
        "leakage_note": (
            "Random sample-level split: the same contexts/chunks can appear in "
            "train and dev/test. Eval is useful for format/behavior trends but is "
            "optimistic for groundedness. Use a document-level split for a clean benchmark."
        ),
        "verification_errors": errors[:20],
    }
    write_json(splits_dir / "split_manifest.json", manifest)
    print({
        "total": manifest["total"],
        "counts": counts,
        "gold_dev": len(list(read_jsonl(splits_dir / "gold_dev_100.jsonl"))),
        "gold_test": len(list(read_jsonl(splits_dir / "gold_test_100.jsonl"))),
        "verification_errors": len(errors),
        "leakage_chunk_overlap": len(leak["chunk_overlap"]),
        "leakage_doc_overlap": len(leak["doc_overlap"]),
    })


if __name__ == "__main__":
    main()
