from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "local" / "src"))

from kb_sft_data.config import DataConfig  # noqa: E402
from kb_sft_data.io_utils import read_jsonl, write_json, write_jsonl  # noqa: E402
from kb_sft_data.verifier import verify_sample  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    cfg = DataConfig.load()
    src = Path(args.input) if args.input else cfg.path("candidates_dir") / "candidates.jsonl"
    if not src.exists():
        raise SystemExit(f"missing {src}; run 07_generate_qa.py")
    verified_path = cfg.path("verified_dir") / "verified.jsonl"
    rejected_path = cfg.path("rejected_dir") / "rule_rejected.jsonl"
    verified, rejected = [], []
    reason_counts: Counter[str] = Counter()
    for sample in read_jsonl(src):
        ok, reasons = verify_sample(sample)
        sample["metadata"]["rule_pass"] = ok
        sample["metadata"]["rule_errors"] = reasons
        if ok:
            verified.append(sample)
        else:
            rejected.append(sample)
            for reason in reasons:
                reason_counts[reason.split(":")[0]] += 1
    write_jsonl(verified_path, verified)
    write_jsonl(rejected_path, rejected)
    stats = {
        "input": len(verified) + len(rejected),
        "verified": len(verified),
        "rejected": len(rejected),
        "pass_rate": round(len(verified) / max(len(verified) + len(rejected), 1), 4),
        "top_reasons": reason_counts.most_common(20),
        "verified_path": str(verified_path),
        "rejected_path": str(rejected_path),
    }
    write_json(cfg.path("verified_dir") / "rule_stats.json", stats)
    print(stats)


if __name__ == "__main__":
    main()
