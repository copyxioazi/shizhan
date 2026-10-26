from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PACKAGE_DIR = Path(__file__).resolve().parent
LOCAL_DIR = PACKAGE_DIR.parents[1]          # .../local
PROJECT_ROOT = LOCAL_DIR.parent             # .../model_train
SHARED_DIR = PROJECT_ROOT / "shared"
DATA_DIR = PROJECT_ROOT / "data"


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader; never overrides existing env vars."""
    path = path or (PROJECT_ROOT / ".env")
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def project_path(value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else PROJECT_ROOT / p


def load_yaml(path: str | Path) -> dict[str, Any]:
    with open(project_path(path), encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def api_settings() -> dict[str, Any]:
    load_dotenv()
    return {
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "generator_model": os.getenv("GENERATOR_MODEL", "deepseek-chat"),
        "judge_model": os.getenv("JUDGE_MODEL", "deepseek-reasoner"),
        "budget_usd": float(os.getenv("DATA_BUDGET_USD", "30")),
        "price_input_per_m": float(os.getenv("PRICE_INPUT_PER_M", "0.27")),
        "price_output_per_m": float(os.getenv("PRICE_OUTPUT_PER_M", "1.10")),
    }


@dataclass
class GenerationConfig:
    concurrency: int = 8
    timeout_s: int = 120
    max_retries: int = 5
    candidates_per_bundle: int = 3
    budget_usd: float = 30.0
    target_counts: dict[str, dict[str, int]] = field(default_factory=dict)


@dataclass
class RetrievalConfig:
    mode: str = "auto"
    top_k: int = 10
    dense_weight: float = 0.8
    sparse_weight: float = 0.2
    min_context: int = 3
    max_context: int = 10
    abs_gap: float = 0.10
    rel_gap: float = 0.25
    entity_filter_rate: float = 0.8
    shuffle_contexts: bool = True


@dataclass
class DataConfig:
    paths: dict[str, str]
    corpus: dict[str, Any]
    generation: GenerationConfig
    retrieval: RetrievalConfig
    seed: int = 42

    @classmethod
    def load(cls, path: str | Path = "local/configs/data.yaml") -> "DataConfig":
        raw = load_yaml(path)
        return cls(
            paths=raw.get("paths", {}),
            corpus=raw.get("corpus", {}),
            generation=GenerationConfig(**raw.get("generation", {})),
            retrieval=RetrievalConfig(**raw.get("retrieval", {})),
            seed=int(raw.get("seed", 42)),
        )

    def path(self, key: str) -> Path:
        return project_path(self.paths[key])

    def ensure_dirs(self) -> None:
        for key in (
            "raw_dir",
            "corpus_dir",
            "canon_dir",
            "candidates_dir",
            "verified_dir",
            "rejected_dir",
            "splits_dir",
        ):
            if key in self.paths:
                self.path(key).mkdir(parents=True, exist_ok=True)
