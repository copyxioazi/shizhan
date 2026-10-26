from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "local" / "src"))

from kb_sft_data.config import DataConfig, api_settings, project_path  # noqa: E402


def has(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def main() -> None:
    cfg = DataConfig.load()
    settings = api_settings()
    seed = cfg.corpus.get("seed", {})
    report = {
        "python": sys.version.split()[0],
        "project_root": str(ROOT),
        "packages": {
            name: has(name)
            for name in ("openai", "yaml", "numpy", "fitz", "jsonschema", "rank_bm25", "FlagEmbedding")
        },
        "api_key_present": bool(settings["api_key"]),
        "base_url": settings["base_url"],
        "generator_model": settings["generator_model"],
        "judge_model": settings["judge_model"],
        "budget_usd": settings["budget_usd"],
        "seed_files": {
            "hak180_split": str(project_path(seed.get("hak180_split", ""))),
            "hak180_split_exists": project_path(seed.get("hak180_split", "")).exists(),
            "multimeter_pdf_exists": project_path(seed.get("multimeter_pdf", "")).exists(),
        },
        "bge_model": project_path("D:/AAAA/models/models/BAAI--bge-m3/snapshots/master").exists(),
        "corpus_exists": (cfg.path("corpus_dir") / "corpus.jsonl").exists(),
        "embeddings_exist": (cfg.path("corpus_dir") / "embeddings.npz").exists(),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["api_key_present"]:
        print("\n[tip] 没有 DEEPSEEK_API_KEY：先用 07_generate_qa.py --offline 跑冒烟，再填 .env。")
    if not report["packages"]["jsonschema"]:
        print("[warn] jsonschema 未安装：pip install -e local")


if __name__ == "__main__":
    main()
