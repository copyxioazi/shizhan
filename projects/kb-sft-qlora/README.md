# 掌柜智库 Qwen3-8B QLoRA

Design: [DESIGN.md](DESIGN.md). Original requirements: [智库微调.md](智库微调.md).

Data is built locally (CPU), frozen, then uploaded and trained on a ModelScope
free 24 GB GPU. Training never calls an API and never builds data.

## Layout

- `local/` — CPU data pipeline (`kb_sft_data`), own `pyproject.toml`.
- `cloud/` — GPU QLoRA training/eval (`kb_sft_train`), own `pyproject.toml`.
- `shared/` — canonical prompt templates and JSON schema (not a Python package).
- `data/` — corpora, candidates, final splits (artifacts, not code).

本仓库只提交代码、配置和文档；`data/`、`dist/`、`runs/` 是管线生成的产物，
不纳入版本控制。要复现实验，先按下面的步骤在本地重建数据，
再用 `13_export_upload.py` 生成云端上传包。

## Local data pipeline

```bash
cd projects/kb-sft-qlora
cp .env.example .env      # fill DEEPSEEK_API_KEY
pip install -e local
# optional BGE-M3 embeddings; otherwise BM25 fallback is used
pip install -e "local[bge]"

python local/scripts/00_probe_env.py
python local/scripts/01_convert_pdf.py
python local/scripts/02_generate_docs.py --dry-run 2
python local/scripts/02_generate_docs.py
python local/scripts/03_build_corpus.py
python local/scripts/04_embed_corpus.py        # optional
python local/scripts/05_freeze_corpus.py
python local/scripts/06_retrieve_sim.py --audit 20
python local/scripts/07_generate_qa.py --task faithful --limit 20
python local/scripts/07_generate_qa.py
python local/scripts/08_verify_rule.py
python local/scripts/09_judge.py
python local/scripts/10_build_dataset.py
python local/scripts/11_dedup_split.py
python local/scripts/12_validate_dataset.py
```

The pipeline is resumable: generation checkpoints every 50 items into
`data/candidates/`, and every script skips already-written outputs unless
`--force` is passed.

### One-file upload

```bash
python local/scripts/13_export_upload.py
```

This writes `dist/kb_sft_all.jsonl` (train+dev+test in one file, with
`split`/`metadata.split`) and `dist/kb_sft_bundle.tar.gz` (one upload file
containing the data, gold rows, manifest, shared templates/schema, and the
`cloud/` project). Upload the tarball and extract it at
`/mnt/data/model_train`; `cloud/configs/*.yaml` already point at
`data/kb_sft_all.jsonl`.

Judge model note: `deepseek-reasoner` is the quality option but is much slower
and more expensive for ~7k candidates. For the full pass use
`JUDGE_MODEL=deepseek-chat python local/scripts/09_judge.py --concurrency 16`;
reserve the reasoner for the 200-case gold calibration if you want it.

## Cloud training (ModelScope 24 GB)

云端步骤基于上传包解压后的目录（数据文件不在本仓库中）：

```bash
cd /mnt/data/model_train
export HF_HOME=/mnt/data/hf MODELSCOPE_CACHE=/mnt/data/ms TMPDIR=/mnt/data/tmp

python cloud/scripts/00_probe_cloud.py
pip install -e cloud
modelscope download --model Qwen/Qwen3-8B --local_dir /mnt/data/models/Qwen3-8B

python cloud/scripts/14_smoke_test.py --config cloud/configs/train_qlora.yaml
nohup python cloud/scripts/13_train_qlora.py \
  --config cloud/configs/train_qlora.yaml --resume auto \
  > /mnt/data/out/train.log 2>&1 &

# after training
python cloud/scripts/15_eval.py --config cloud/configs/eval.yaml --adapter none
python cloud/scripts/15_eval.py --config cloud/configs/eval.yaml \
  --adapter runs/qwen3-8b-kb-lora
python cloud/scripts/16_report.py --config cloud/configs/eval.yaml
```

The adapter is the deliverable. This project does not merge 8B weights or
serve a deployment endpoint.

## Tests

```bash
# local (no GPU)
pytest local/tests -q
# cloud (CPU is enough for template/renderer tests)
pytest cloud/tests -q
```

## Known unknowns (probe before full training)

- ModelScope free instance time limit, persistent-disk mount, outbound network.
- `bitsandbytes==0.50.1` against CUDA 13.0.3 — `00_probe_cloud.py` runs a
  `Linear4bit` kernel test; fall back to fp16 compute, then Unsloth, then bf16 LoRA.
- Qwen3-8B chat template vs the local 0.6B template — dump and diff.
- TRL 0.24 `completion_only_loss` behavior — the 200-step smoke test catches it.
