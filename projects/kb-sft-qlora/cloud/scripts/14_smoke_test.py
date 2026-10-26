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
    parser.add_argument("--max-samples", type=int, default=0)
    parser.add_argument("--max-steps", type=int, default=0)
    args = parser.parse_args()

    cfg = TrainConfig.load(args.config)
    state = train(
        cfg,
        smoke=True,
        max_samples=args.max_samples or int(cfg.smoke.get("max_samples", 200)),
        max_steps=args.max_steps or int(cfg.smoke.get("max_steps", 20)),
        resume="none",
    )
    smoke_dir = Path(str(cfg.path(cfg.output_dir)) + "-smoke")
    checks = {
        "output_dir": str(smoke_dir),
        "adapter_config": (smoke_dir / "adapter_config.json").exists(),
        "run_state": (smoke_dir / "RUN_STATE.json").exists(),
        "state": state,
    }
    print(json.dumps(checks, ensure_ascii=False, indent=2, default=str))
    if not checks["adapter_config"]:
        raise SystemExit("smoke failed: adapter_config.json not written")
    if state.get("peak_vram_gb") and state["peak_vram_gb"] > 23.5:
        print("[warn] peak VRAM near 24GB; reduce max_length to 3072.")


if __name__ == "__main__":
    main()
