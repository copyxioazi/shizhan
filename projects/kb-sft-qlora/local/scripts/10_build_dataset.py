from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "local" / "src"))

from kb_sft_data.config import DataConfig  # noqa: E402
from kb_sft_data.io_utils import read_jsonl, write_json, write_jsonl  # noqa: E402


def _score(sample: dict) -> tuple[float, str]:
    judge = sample.get("metadata", {}).get("judge") or {}
    values = [
        judge.get("faithfulness", 0), judge.get("citation_correctness", 0),
        judge.get("completeness", 0), judge.get("format", 0),
    ]
    try:
        mean = sum(float(v) for v in values) / 4
    except (TypeError, ValueError):
        mean = 0.0
    return mean, sample.get("id", "")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-unjudged", action="store_true")
    args = parser.parse_args()

    cfg = DataConfig.load()
    src = cfg.path("verified_dir") / "judged.jsonl"
    if not src.exists():
        raise SystemExit(f"missing {src}; run 09_judge.py")
    rows = list(read_jsonl(src))
    accepted = []
    for sample in rows:
        meta = sample.get("metadata", {})
        if not meta.get("rule_pass"):
            continue
        judge = meta.get("judge") or {}
        if judge.get("accept") is True:
            accepted.append(sample)
        elif args.allow_unjudged and judge.get("skipped"):
            accepted.append(sample)

    selected: list[dict] = []
    report: dict = {"targets": {}, "selected": {}, "shortfalls": {}}
    by_split_type: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for sample in accepted:
        key = (sample.get("metadata", {}).get("split", ""), sample.get("task_type", ""))
        by_split_type[key].append(sample)

    for split, targets in cfg.generation.target_counts.items():
        report["targets"][split] = targets
        report["selected"][split] = {}
        report["shortfalls"][split] = {}
        for task_type, target in targets.items():
            items = sorted(by_split_type.get((split, task_type), []), key=_score, reverse=True)
            take = items[:target]
            selected.extend(take)
            report["selected"][split][task_type] = len(take)
            if len(take) < target:
                report["shortfalls"][split][task_type] = target - len(take)

    out = cfg.path("splits_dir") / "_pool.jsonl"
    write_jsonl(out, selected)
    report["total_selected"] = len(selected)
    report["by_split"] = dict(Counter(s["metadata"]["split"] for s in selected))
    write_json(cfg.path("splits_dir") / "selection_report.json", report)
    print(f"selected {len(selected)} -> {out}")
    print(report)


if __name__ == "__main__":
    main()
