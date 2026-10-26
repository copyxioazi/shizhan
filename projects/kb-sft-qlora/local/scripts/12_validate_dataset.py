from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "local" / "src"))

from kb_sft_data.config import DataConfig  # noqa: E402
from kb_sft_data.io_utils import read_json, read_jsonl, write_json  # noqa: E402
from kb_sft_data.splitter import leakage_report  # noqa: E402
from kb_sft_data.templates import CITATION_HEADER  # noqa: E402
from kb_sft_data.verifier import verify_sample  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-overlap", action="store_true",
                        help="allow train/dev/test context overlap after a random resplit")
    args = parser.parse_args()

    cfg = DataConfig.load()
    splits_dir = cfg.path("splits_dir")
    report: dict = {"splits": {}, "errors": {}, "warnings": []}
    all_samples = []
    hard_fail = False

    for split in ("train", "dev", "test"):
        path = splits_dir / f"{split}.jsonl"
        if not path.exists():
            report["errors"][split] = "missing file"
            hard_fail = True
            continue
        rows = list(read_jsonl(path))
        all_samples.extend(rows)
        errors = []
        token_counts = []
        for sample in rows:
            ok, reasons = verify_sample(sample)
            if not ok:
                errors.append({"id": sample.get("id"), "reasons": reasons})
            token_counts.append(sample.get("metadata", {}).get("token_counts", {}).get("prompt", 0))
            if sample.get("expected_behavior") in ("answer", "partial", "conflict"):
                if CITATION_HEADER not in sample["messages"][2]["content"]:
                    errors.append({"id": sample.get("id"), "reasons": ["missing source block"]})
            if sample.get("expected_behavior") == "refuse" and CITATION_HEADER in sample["messages"][2]["content"]:
                errors.append({"id": sample.get("id"), "reasons": ["refusal has source block"]})
        target = sum(cfg.generation.target_counts.get(split, {}).values())
        p99 = 0
        if token_counts:
            ordered = sorted(token_counts)
            p99 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))]
        report["splits"][split] = {
            "count": len(rows),
            "target": target,
            "error_count": len(errors),
            "token_p99_approx": p99,
        }
        if errors:
            report["errors"][split] = errors[:50]
            hard_fail = True
        if len(rows) < target:
            report["warnings"].append(f"{split}: {len(rows)} < target {target}")

    leak = leakage_report(all_samples)
    report["leakage"] = leak
    if not leak["ok"]:
        if args.allow_overlap:
            report["warnings"].append(
                "train/dev/test context overlap present (random resplit; eval is optimistic)"
            )
        else:
            hard_fail = True
    for split in ("dev", "test"):
        path = splits_dir / f"gold_{split}_100.jsonl"
        report[f"gold_{split}"] = len(list(read_jsonl(path))) if path.exists() else 0
        if report[f"gold_{split}"] != 100:
            report["warnings"].append(f"gold_{split} count != 100")
    report["ok"] = not hard_fail
    out = ROOT / "reports" / "data_validation.json"
    write_json(out, report)
    print(json.dumps(report, ensure_ascii=False, indent=2)[:4000])
    print(f"report -> {out}")
    if hard_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
