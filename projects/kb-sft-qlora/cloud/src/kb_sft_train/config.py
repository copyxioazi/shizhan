from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CLOUD_DIR = Path(__file__).resolve().parents[2]      # .../cloud
PROJECT_ROOT = CLOUD_DIR.parent                     # parent of the package
# The upload bundle is self-contained: prefer cloud/shared, fall back to
# <project>/shared for development inside the repo.
_SHARED_IN_CLOUD = CLOUD_DIR / "shared"
SHARED_DIR = _SHARED_IN_CLOUD if _SHARED_IN_CLOUD.exists() else PROJECT_ROOT / "shared"


def project_path(value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else PROJECT_ROOT / p


def load_yaml(path: str | Path) -> dict[str, Any]:
    with open(project_path(path), encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class TrainConfig:
    model_id: str
    model_local_dir: str
    train_file: str
    dev_file: str
    output_dir: str
    seed: int
    quantization: dict[str, Any]
    lora: dict[str, Any]
    sft: dict[str, Any]
    smoke: dict[str, Any]
    source_path: str = ""

    @classmethod
    def load(cls, path: str | Path = "cloud/configs/train_qlora.yaml") -> "TrainConfig":
        raw = load_yaml(path)
        return cls(
            model_id=raw.get("model_id", "Qwen/Qwen3-8B"),
            model_local_dir=raw.get("model_local_dir", ""),
            train_file=raw.get("train_file", "data/splits/train.jsonl"),
            dev_file=raw.get("dev_file", "data/splits/dev.jsonl"),
            output_dir=raw.get("output_dir", "runs/qwen3-8b-kb-lora"),
            seed=int(raw.get("seed", 42)),
            quantization=raw.get("quantization", {}),
            lora=raw.get("lora", {}),
            sft=raw.get("sft", {}),
            smoke=raw.get("smoke", {}),
            source_path=str(project_path(path)),
        )

    def resolve_model(self) -> str:
        if self.model_local_dir and Path(self.model_local_dir).exists():
            return self.model_local_dir
        local = PROJECT_ROOT / "models" / "Qwen3-8B"
        if local.exists():
            return str(local)
        return self.model_id

    def path(self, value: str | Path) -> Path:
        return project_path(value)


@dataclass
class EvalConfig:
    model_id: str
    model_local_dir: str
    test_file: str
    adapter_dir: str
    output_dir: str
    max_new_tokens: int
    batch_size: int
    load_in_4bit: bool
    bf16: bool
    temperature: float
    do_sample: bool
    seed: int
    limit: int
    source_path: str = ""

    @classmethod
    def load(cls, path: str | Path = "cloud/configs/eval.yaml") -> "EvalConfig":
        raw = load_yaml(path)
        return cls(
            model_id=raw.get("model_id", "Qwen/Qwen3-8B"),
            model_local_dir=raw.get("model_local_dir", ""),
            test_file=raw.get("test_file", "data/splits/test.jsonl"),
            adapter_dir=raw.get("adapter_dir", "runs/qwen3-8b-kb-lora"),
            output_dir=raw.get("output_dir", "runs/eval"),
            max_new_tokens=int(raw.get("max_new_tokens", 768)),
            batch_size=int(raw.get("batch_size", 1)),
            load_in_4bit=bool(raw.get("load_in_4bit", True)),
            bf16=bool(raw.get("bf16", True)),
            temperature=float(raw.get("temperature", 0.0)),
            do_sample=bool(raw.get("do_sample", False)),
            seed=int(raw.get("seed", 42)),
            limit=int(raw.get("limit", 0)),
            source_path=str(project_path(path)),
        )

    def resolve_model(self) -> str:
        if self.model_local_dir and Path(self.model_local_dir).exists():
            return self.model_local_dir
        local = PROJECT_ROOT / "models" / "Qwen3-8B"
        if local.exists():
            return str(local)
        return self.model_id

    def path(self, value: str | Path) -> Path:
        return project_path(value)
