from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT, TrainConfig
from .io_utils import sha256_file
from .schema import load_split
from .tokenize import has_think, rows_to_records


def _sha256(path: str | Path) -> str:
    p = Path(path)
    return sha256_file(p) if p.exists() else ""


def _latest_checkpoint(output_dir: Path) -> str | None:
    checkpoints = [p for p in output_dir.glob("checkpoint-*") if p.is_dir()]
    if not checkpoints:
        return None

    def step(p: Path) -> int:
        try:
            return int(p.name.split("-")[-1])
        except ValueError:
            return -1

    return str(sorted(checkpoints, key=step)[-1])


def _load_causal_lm(path: str, dtype, **kwargs):
    from transformers import AutoModelForCausalLM

    try:
        return AutoModelForCausalLM.from_pretrained(path, dtype=dtype, **kwargs)
    except TypeError:
        return AutoModelForCausalLM.from_pretrained(path, torch_dtype=dtype, **kwargs)


def load_tokenizer(model_path: str):
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"
    return tokenizer


def load_model(cfg: TrainConfig, tokenizer):
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

    capability = torch.cuda.get_device_capability(0) if torch.cuda.is_available() else (0, 0)
    dtype = torch.bfloat16 if capability[0] >= 8 else torch.float16
    quantization_config = None
    compute_name = str(cfg.quantization.get("bnb_4bit_compute_dtype", "bfloat16")).lower()
    compute_dtype = {
        "bfloat16": torch.bfloat16,
        "bf16": torch.bfloat16,
        "float16": torch.float16,
        "fp16": torch.float16,
    }.get(compute_name, dtype)
    if cfg.quantization.get("load_in_4bit", True):
        from transformers import BitsAndBytesConfig

        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type=cfg.quantization.get("bnb_4bit_quant_type", "nf4"),
            bnb_4bit_compute_dtype=compute_dtype,
            bnb_4bit_use_double_quant=cfg.quantization.get("bnb_4bit_use_double_quant", True),
        )

    model = _load_causal_lm(
        cfg.resolve_model(),
        dtype,
        quantization_config=quantization_config,
        device_map={"": 0},
        attn_implementation="sdpa",
        trust_remote_code=True,
    )
    model.config.use_cache = False
    if quantization_config is not None:
        try:
            model = prepare_model_for_kbit_training(
                model,
                use_gradient_checkpointing=True,
                gradient_checkpointing_kwargs={"use_reentrant": False},
            )
        except TypeError:
            model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    else:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})

    lora_cfg = cfg.lora
    lora = LoraConfig(
        r=int(lora_cfg.get("r", 16)),
        lora_alpha=int(lora_cfg.get("alpha", 32)),
        lora_dropout=float(lora_cfg.get("dropout", 0.05)),
        bias=lora_cfg.get("bias", "none"),
        task_type=lora_cfg.get("task_type", "CAUSAL_LM"),
        target_modules=lora_cfg.get(
            "target_modules",
            ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        ),
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()
    return model, dtype, capability


def build_sft_config(cfg: TrainConfig, output_dir: Path, *, smoke: bool, max_steps: int = 0):
    from trl import SFTConfig

    sft = cfg.sft
    fields = set(SFTConfig.__dataclass_fields__)
    kwargs: dict[str, Any] = {
        "output_dir": str(output_dir),
        "per_device_train_batch_size": int(sft.get("per_device_train_batch_size", 1)),
        "gradient_accumulation_steps": int(sft.get("gradient_accumulation_steps", 16)),
        "num_train_epochs": float(sft.get("num_train_epochs", 2)),
        "learning_rate": float(sft.get("learning_rate", 1e-4)),
        "lr_scheduler_type": sft.get("lr_scheduler_type", "cosine"),
        "warmup_ratio": float(sft.get("warmup_ratio", 0.03)),
        "weight_decay": float(sft.get("weight_decay", 0.01)),
        "max_grad_norm": float(sft.get("max_grad_norm", 1.0)),
        "bf16": bool(sft.get("bf16", True)),
        "fp16": bool(sft.get("fp16", False)),
        "optim": sft.get("optim", "paged_adamw_8bit"),
        "gradient_checkpointing": bool(sft.get("gradient_checkpointing", True)),
        "gradient_checkpointing_kwargs": {"use_reentrant": False},
        "logging_steps": int(sft.get("logging_steps", 10)),
        "save_strategy": "steps",
        "save_steps": int(sft.get("save_steps", 100)),
        "save_total_limit": int(sft.get("save_total_limit", 3)),
        "report_to": "none",
        "remove_unused_columns": False,
        "dataloader_num_workers": int(sft.get("dataloader_num_workers", 2)),
        "seed": cfg.seed,
        "packing": bool(sft.get("packing", False)),
        "completion_only_loss": bool(sft.get("completion_only_loss", True)),
    }
    max_length = int(sft.get("max_length", 4096))
    if "max_length" in fields:
        kwargs["max_length"] = max_length
    elif "max_seq_length" in fields:
        kwargs["max_seq_length"] = max_length
    if "eval_strategy" in fields:
        kwargs["eval_strategy"] = "no"
    elif "evaluation_strategy" in fields:
        kwargs["evaluation_strategy"] = "no"
    if smoke:
        kwargs["num_train_epochs"] = 1.0
        kwargs["max_steps"] = max_steps or 20
        kwargs["save_steps"] = max(5, (max_steps or 20))
        kwargs["logging_steps"] = 1
    kwargs = {k: v for k, v in kwargs.items() if k in fields}
    return SFTConfig(**kwargs)


def build_trainer(model, tokenizer, sft_config, dataset):
    from trl import SFTTrainer

    params = inspect.signature(SFTTrainer.__init__).parameters
    kwargs: dict[str, Any] = {"model": model, "args": sft_config, "train_dataset": dataset}
    if "processing_class" in params:
        kwargs["processing_class"] = tokenizer
    else:
        kwargs["tokenizer"] = tokenizer
    return SFTTrainer(**kwargs)


class RunStateCallback:
    """Lightweight callback factory; avoids importing TrainerCallback when unused."""

    @staticmethod
    def make(output_dir: Path, meta: dict[str, Any]):
        from transformers import TrainerCallback

        class _Callback(TrainerCallback):
            def _write(self, state) -> None:
                payload = {
                    **meta,
                    "global_step": state.global_step,
                    "epoch": state.epoch,
                    "log_history": state.log_history[-30:],
                }
                (output_dir / "RUN_STATE.json").write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
                )

            def on_save(self, args, state, control, **kwargs):
                self._write(state)

            def on_train_end(self, args, state, control, **kwargs):
                self._write(state)

        return _Callback()


def train(
    cfg: TrainConfig,
    *,
    smoke: bool = False,
    max_samples: int = 0,
    max_steps: int = 0,
    resume: str = "auto",
) -> dict[str, Any]:
    import torch
    from datasets import Dataset

    limit = max_samples or (int(cfg.smoke.get("max_samples", 200)) if smoke else 0)
    rows = load_split(cfg.path(cfg.train_file), split="train", limit=limit)
    tokenizer = load_tokenizer(cfg.resolve_model())
    records, skipped = rows_to_records(rows, tokenizer)
    if not records:
        raise SystemExit("no training records after filtering")
    dataset = Dataset.from_list(records)

    model, dtype, capability = load_model(cfg, tokenizer)
    output_dir = cfg.path(cfg.output_dir)
    if smoke:
        output_dir = Path(str(output_dir) + "-smoke")
    output_dir.mkdir(parents=True, exist_ok=True)

    sft_config = build_sft_config(cfg, output_dir, smoke=smoke, max_steps=max_steps)
    if capability[0] < 8:
        sft_config.bf16 = False
        sft_config.fp16 = True
    trainer = build_trainer(model, tokenizer, sft_config, dataset)

    resume_path = _latest_checkpoint(output_dir) if resume == "auto" else (
        None if resume in ("none", "", None) else resume
    )
    meta = {
        "model": cfg.resolve_model(),
        "capability": list(capability),
        "dtype": str(dtype),
        "dataset_sha256": _sha256(cfg.path(cfg.train_file)),
        "config_sha256": _sha256(cfg.source_path),
        "train_records": len(records),
        "skipped_think_records": skipped[:20],
        "lora_r": cfg.lora.get("r", 16),
        "lora_alpha": cfg.lora.get("alpha", 32),
        "max_length": cfg.sft.get("max_length", 4096),
        "resume_from": resume_path,
        "smoke": smoke,
        "peak_vram_gb": None,
    }
    trainer.add_callback(RunStateCallback.make(output_dir, meta))
    trainer.train(resume_from_checkpoint=resume_path)
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))

    if torch.cuda.is_available():
        meta["peak_vram_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 3)
    meta.update(
        {
            "global_step": trainer.state.global_step,
            "epoch": trainer.state.epoch,
            "log_history_tail": trainer.state.log_history[-10:],
        }
    )
    (output_dir / "RUN_STATE.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return meta
