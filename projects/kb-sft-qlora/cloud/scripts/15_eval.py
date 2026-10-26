from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cloud" / "src"))

from kb_sft_train.config import EvalConfig  # noqa: E402
from kb_sft_train.evaluate import run_eval  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="cloud/configs/eval.yaml")
    parser.add_argument("--adapter", default="none", help="none | base | /path/to/adapter")
    parser.add_argument("--output", default="")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    cfg = EvalConfig.load(args.config)
    if args.limit:
        cfg.limit = args.limit
    label = "base" if args.adapter in ("none", "base", "") else "adapter"
    adapter = None if label == "base" else str(cfg.path(args.adapter))
    output = Path(args.output) if args.output else cfg.path(cfg.output_dir) / f"pred_{label}.jsonl"
    result = run_eval(cfg, adapter, output)
    print(json.dumps({**result, "label": label}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
