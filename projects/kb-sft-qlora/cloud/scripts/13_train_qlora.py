from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cloud" / "src"))

from kb_sft_train.config import TrainConfig  # noqa: E402
from kb_sft_train.train_utils import train  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="cloud/configs/train_qlora.yaml")
    parser.add_argument("--resume", default="auto", help="auto | none | /path/to/checkpoint-*")
    parser.add_argument("--max-samples", type=int, default=0)
    parser.add_argument("--max-steps", type=int, default=0)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    cfg = TrainConfig.load(args.config)
    state = train(
        cfg,
        smoke=args.smoke,
        max_samples=args.max_samples,
        max_steps=args.max_steps,
        resume=args.resume,
    )
    print(json.dumps(state, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
