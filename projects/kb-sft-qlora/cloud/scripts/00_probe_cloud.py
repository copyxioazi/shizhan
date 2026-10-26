from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cloud" / "src"))

from kb_sft_train.config import CLOUD_DIR, SHARED_DIR, TrainConfig  # noqa: E402


def run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception as exc:
        return f"<error: {exc}>"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="cloud/configs/train_qlora.yaml")
    parser.add_argument("--model", default="")
    parser.add_argument("--dump-template", action="store_true")
    args = parser.parse_args()

    report: dict = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "cwd": os.getcwd(),
        "nvidia_smi": run(["nvidia-smi"]),
        "disk": run(["df", "-h"]),
        "mounts": run(["sh", "-c", "mount | grep -E 'mnt|workspace' || true"]),
        "env": {k: os.getenv(k) for k in ("HF_HOME", "MODELSCOPE_CACHE", "TMPDIR", "DEEPSEEK_API_KEY")},
        "model_scope_data": Path("/mnt/data").exists(),
        "packages": {},
    }
    report["env"]["DEEPSEEK_API_KEY"] = bool(report["env"]["DEEPSEEK_API_KEY"])

    try:
        import torch

        report["torch"] = {
            "version": torch.__version__,
            "cuda": torch.version.cuda,
            "available": torch.cuda.is_available(),
            "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "capability": list(torch.cuda.get_device_capability(0)) if torch.cuda.is_available() else None,
            "vram_gb": round(torch.cuda.get_device_properties(0).total_memory / 1e9, 2) if torch.cuda.is_available() else None,
        }
    except Exception as exc:
        report["torch"] = {"error": str(exc)}

    for name in ("transformers", "peft", "trl", "datasets", "accelerate", "bitsandbytes", "modelscope"):
        try:
            module = __import__(name)
            report["packages"][name] = getattr(module, "__version__", "?")
        except Exception as exc:
            report["packages"][name] = f"<error: {exc}>"

    try:
        import torch
        import bitsandbytes as bnb

        layer = bnb.nn.Linear4bit(16, 16, quant_type="nf4", compute_dtype=torch.bfloat16).cuda()
        out = layer(torch.randn(2, 16, device="cuda", dtype=torch.bfloat16))
        report["bnb_linear4bit"] = {"ok": True, "shape": list(out.shape), "version": bnb.__version__}
    except Exception as exc:
        report["bnb_linear4bit"] = {"ok": False, "error": str(exc)}

    cfg = TrainConfig.load(args.config)
    model_path = args.model or cfg.resolve_model()
    report["model_path"] = model_path
    report["model_exists"] = Path(model_path).exists()
    if args.dump_template:
        try:
            from transformers import AutoTokenizer

            tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
            template = tokenizer.chat_template or ""
            out = SHARED_DIR / "templates" / "qwen3_nonthinking.jinja"
            out.write_text(template, encoding="utf-8")
            report["template_dump"] = str(out)
            report["template_has_enable_thinking"] = "enable_thinking" in template
        except Exception as exc:
            report["template_dump_error"] = str(exc)

    (CLOUD_DIR / "runs").mkdir(parents=True, exist_ok=True)
    (CLOUD_DIR / "runs" / "probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if not report.get("torch", {}).get("available"):
        raise SystemExit("CUDA is not available; QLoRA training cannot start.")
    if not report.get("bnb_linear4bit", {}).get("ok"):
        print(
            "\n[fallback] bitsandbytes Linear4bit failed. Set "
            "bnb_4bit_compute_dtype: float16 and optim: adamw_torch in "
            "cloud/configs/train_qlora.yaml, then retry. Last resort: "
            "load_in_4bit: false with max_length: 2048 (bf16 LoRA, tight on 24GB)."
        )
    if not report.get("model_exists"):
        print(f"\n[download] modelscope download --model Qwen/Qwen3-8B --local_dir {model_path}")


if __name__ == "__main__":
    main()
