from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cloud" / "src"))

from kb_sft_train.config import EvalConfig  # noqa: E402
from kb_sft_train.report import compare, load_predictions  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="cloud/configs/eval.yaml")
    parser.add_argument("--base", default="")
    parser.add_argument("--adapter", default="")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    cfg = EvalConfig.load(args.config)
    out_dir = cfg.path(cfg.output_dir)
    base_path = Path(args.base) if args.base else out_dir / "pred_base.jsonl"
    adapter_path = Path(args.adapter) if args.adapter else out_dir / "pred_adapter.jsonl"
    if not base_path.exists() or not adapter_path.exists():
        raise SystemExit(f"missing predictions: {base_path} / {adapter_path}. Run 15_eval.py twice.")
    report = compare(load_predictions(base_path), load_predictions(adapter_path), out_dir)
    print((out_dir / "report.md").read_text(encoding="utf-8"))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
