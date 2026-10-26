from __future__ import annotations

import argparse
import shutil
import tarfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys_path = ROOT / "local" / "src"
import sys

sys.path.insert(0, str(sys_path))

from kb_sft_data.config import DataConfig  # noqa: E402
from kb_sft_data.io_utils import now_iso, read_json, read_jsonl, sha256_file, write_json, write_jsonl  # noqa: E402

UPLOAD_MD = """# Cloud upload

This bundle is self-contained. Extract it so that `cloud/` sits under
`/mnt/data/model_train`; the scripts resolve data relative to the parent of
`cloud/`.

## 1. Upload and extract

```bash
mkdir -p /mnt/data/model_train
tar -xzf /mnt/data/kb_sft_bundle.tar.gz -C /mnt/data/model_train
cd /mnt/data/model_train
```

- `cloud/data/kb_sft_all.jsonl` — 2,884 rows; `split` / `metadata.split`
  gives 2,308 train / 288 dev / 288 test.
- `cloud/data/gold_dev_100.jsonl`, `cloud/data/gold_test_100.jsonl` — 200
  human-review rows.
- `cloud/data/split_manifest.json` — counts and the random-split leakage note.
- `cloud/configs/*.yaml` already point at `cloud/data/kb_sft_all.jsonl`.

> The dev/test split is a stratified random sample-level split from train, so
> some contexts appear in both. Eval is useful for format/refusal trends but
> optimistic for groundedness.

## 2. Install and download the model

```bash
export HF_HOME=/mnt/data/hf MODELSCOPE_CACHE=/mnt/data/ms TMPDIR=/mnt/data/tmp
pip install -e cloud
modelscope download --model Qwen/Qwen3-8B --local_dir /mnt/data/models/Qwen3-8B
python cloud/scripts/00_probe_cloud.py --config cloud/configs/train_qlora.yaml --dump-template
```

If the probe reports a bitsandbytes `Linear4bit` failure, set
`bnb_4bit_compute_dtype: float16` in `cloud/configs/train_qlora.yaml` and retry;
the next fallback is Unsloth, then bf16 LoRA.

## 3. Smoke test, then full training

```bash
python cloud/scripts/14_smoke_test.py --config cloud/configs/train_qlora.yaml
nohup python cloud/scripts/13_train_qlora.py \\
  --config cloud/configs/train_qlora.yaml --resume auto \\
  > /mnt/data/out/train.log 2>&1 &
```

Checkpoints are written every 100 steps; if the free session ends, rerun with
`--resume auto`. The adapter is saved under `runs/qwen3-8b-kb-lora/`.

## 4. Evaluate and report

```bash
python cloud/scripts/15_eval.py --config cloud/configs/eval.yaml --adapter none
python cloud/scripts/15_eval.py --config cloud/configs/eval.yaml \\
  --adapter runs/qwen3-8b-kb-lora
python cloud/scripts/16_report.py --config cloud/configs/eval.yaml
```

No merge or deployment is included. The adapter is the deliverable.
"""


def _tar_filter(info: tarfile.TarInfo):
    parts = Path(info.name).parts
    if any(part in {"__pycache__", ".pytest_cache", ".venv", "runs", ".git"} for part in parts):
        return None
    if info.name.endswith((".pyc", ".pyo", ".log", ".tmp")):
        return None
    return info


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="dist")
    parser.add_argument("--no-tar", action="store_true")
    args = parser.parse_args()

    cfg = DataConfig.load()
    splits_dir = cfg.path("splits_dir")
    rows = []
    source_counts: dict[str, dict[str, int]] = {}
    for split in ("train", "dev", "test"):
        path = splits_dir / f"{split}.jsonl"
        if not path.exists():
            raise SystemExit(f"missing {path}; finish 10/11/12 first")
        split_rows = list(read_jsonl(path))
        source_counts[split] = dict(Counter(row.get("task_type", "") for row in split_rows))
        for row in split_rows:
            row["split"] = split
            rows.append(row)

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    all_path = out_dir / "kb_sft_all.jsonl"
    write_jsonl(all_path, rows)

    manifest = {
        "created_at": now_iso(),
        "total": len(rows),
        "counts": source_counts,
        "all_file": {
            "path": str(all_path),
            "sha256": sha256_file(all_path),
            "bytes": all_path.stat().st_size,
        },
        "gold": {
            name: str(splits_dir / name)
            for name in ("gold_dev_100.jsonl", "gold_test_100.jsonl")
            if (splits_dir / name).exists()
        },
    }
    write_json(out_dir / "export_manifest.json", manifest)
    (out_dir / "UPLOAD.md").write_text(UPLOAD_MD, encoding="utf-8")

    # Keep the cloud package self-contained: data + shared templates inside cloud/.
    cloud_data = ROOT / "cloud" / "data"
    cloud_data.mkdir(parents=True, exist_ok=True)
    shutil.copy2(all_path, cloud_data / "kb_sft_all.jsonl")
    for name in ("gold_dev_100.jsonl", "gold_test_100.jsonl", "split_manifest.json"):
        src = splits_dir / name
        if src.exists() and src.stat().st_size > 0:
            shutil.copy2(src, cloud_data / name)
    shutil.copy2(out_dir / "export_manifest.json", cloud_data / "export_manifest.json")
    cloud_shared = ROOT / "cloud" / "shared"
    for sub in ("templates", "schema"):
        src = ROOT / "shared" / sub
        if src.exists():
            shutil.copytree(src, cloud_shared / sub, dirs_exist_ok=True)

    print(f"all-in-one: {all_path} ({len(rows)} rows, {all_path.stat().st_size/1e6:.1f} MB)")
    print(f"cloud data: {cloud_data / 'kb_sft_all.jsonl'}")
    print(f"counts: {source_counts}")

    if args.no_tar:
        return
    bundle = out_dir / "kb_sft_bundle.tar.gz"
    with tarfile.open(bundle, "w:gz") as tar:
        tar.add(ROOT / "cloud", arcname="cloud", filter=_tar_filter)
        tar.add(out_dir / "UPLOAD.md", arcname="UPLOAD.md")
        for rel in ("README.md", "DESIGN.md", ".env.example"):
            path = ROOT / rel
            if path.exists():
                tar.add(path, arcname=rel, filter=_tar_filter)
    print(f"upload bundle: {bundle} ({bundle.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
