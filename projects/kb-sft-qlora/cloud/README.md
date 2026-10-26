# Cloud training package

Self-contained: code, `data/kb_sft_all.jsonl` (train/dev/test), the 200 gold
rows, and `shared/` templates/schema.

## Layout

```
cloud/
  pyproject.toml
  configs/train_qlora.yaml     # train_file: cloud/data/kb_sft_all.jsonl
  configs/eval.yaml            # test_file:  cloud/data/kb_sft_all.jsonl
  data/kb_sft_all.jsonl        # 2,308 train / 288 dev / 288 test
  data/gold_dev_100.jsonl
  data/gold_test_100.jsonl
  data/split_manifest.json
  shared/                      # canonical system/user templates + schema
  scripts/                     # probe, train, smoke, eval, report
  src/kb_sft_train/
  tests/
```

The scripts resolve data relative to the parent of `cloud/`, so extract the
bundle at `/mnt/data/model_train` (creating `model_train/cloud/...`) and run
commands from `/mnt/data/model_train`.

## Install

```bash
cd /mnt/data/model_train
# if the image already has a compatible torch:
pip install -e cloud --no-deps
pip install transformers==5.5.0 peft==0.20.0 trl==0.24.0 datasets==4.3.0 \
  accelerate==1.14.0 bitsandbytes==0.50.1 modelscope==1.39.1 \
  pyyaml numpy tqdm jsonschema
# otherwise:
# pip install -e cloud
```

## Download model and probe

```bash
export HF_HOME=/mnt/data/hf MODELSCOPE_CACHE=/mnt/data/ms TMPDIR=/mnt/data/tmp
modelscope download --model Qwen/Qwen3-8B --local_dir /mnt/data/models/Qwen3-8B
python cloud/scripts/00_probe_cloud.py --config cloud/configs/train_qlora.yaml
```

If `bitsandbytes` `Linear4bit` fails, set `bnb_4bit_compute_dtype: float16`
and `optim: adamw_torch` in `cloud/configs/train_qlora.yaml`, then retry.
Last resort: `load_in_4bit: false` with `max_length: 2048` (bf16 LoRA; tight
on 24 GB).

## Train

```bash
python cloud/scripts/14_smoke_test.py --config cloud/configs/train_qlora.yaml
nohup python cloud/scripts/13_train_qlora.py \
  --config cloud/configs/train_qlora.yaml --resume auto \
  > cloud/runs/train.log 2>&1 &
```

Checkpoints and the adapter are under `cloud/runs/qwen3-8b-kb-lora/`.

## Evaluate

```bash
python cloud/scripts/15_eval.py --config cloud/configs/eval.yaml --adapter none
python cloud/scripts/15_eval.py --config cloud/configs/eval.yaml \
  --adapter cloud/runs/qwen3-8b-kb-lora
python cloud/scripts/16_report.py --config cloud/configs/eval.yaml
```

Caveat: the dev/test split is a random sample-level split from train; the same
contexts can appear in both. Eval is useful for format/refusal trends but is
optimistic for groundedness. See `data/split_manifest.json`.
