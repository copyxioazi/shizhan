from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .io_utils import ensure_dir, sha256_file, write_json, write_jsonl


def group_by_split(samples: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        out[sample.get("metadata", {}).get("split", "")].append(sample)
    return out


def stratified_gold(samples: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        by_type[sample.get("task_type", "")].append(sample)
    for items in by_type.values():
        items.sort(key=lambda s: s["id"])
    selected: list[dict[str, Any]] = []
    index = 0
    types = sorted(by_type)
    while len(selected) < n and any(index < len(by_type[t]) for t in types):
        for task_type in types:
            if index < len(by_type[task_type]) and len(selected) < n:
                sample = dict(by_type[task_type][index])
                sample["gold"] = True
                sample["metadata"] = {
                    **sample.get("metadata", {}),
                    "gold_review": {"status": "pending", "reviewer": "", "notes": ""},
                }
                selected.append(sample)
        index += 1
    return selected


def write_splits(
    samples: list[dict[str, Any]],
    splits_dir: str | Path,
    *,
    gold_per_split: int = 100,
    seed: int = 42,
    corpus_sha256: str = "",
    corpus_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    splits_dir = Path(splits_dir)
    ensure_dir(splits_dir)
    groups = group_by_split(samples)
    counts: dict[str, dict[str, int]] = {}
    for split in ("train", "dev", "test"):
        rows = groups.get(split, [])
        write_jsonl(splits_dir / f"{split}.jsonl", rows)
        counts[split] = dict(Counter(s.get("task_type", "") for s in rows))
    for split in ("dev", "test"):
        rows = groups.get(split, [])
        gold = stratified_gold(rows, gold_per_split)
        write_jsonl(splits_dir / f"gold_{split}_{gold_per_split}.jsonl", gold)
    manifest = {
        "seed": seed,
        "counts": counts,
        "gold_per_split": gold_per_split,
        "corpus_sha256": corpus_sha256,
        "corpus_meta": corpus_meta or {},
        "doc_to_split": {
            doc_id: meta.get("split")
            for doc_id, meta in (corpus_meta or {}).get("docs", {}).items()
        },
        "split_files": {
            split: str(splits_dir / f"{split}.jsonl") for split in ("train", "dev", "test")
        },
    }
    write_json(splits_dir / "split_manifest.json", manifest)
    return manifest


def leakage_report(samples: list[dict[str, Any]]) -> dict[str, Any]:
    train = [s for s in samples if s.get("metadata", {}).get("split") == "train"]
    eval_splits = [s for s in samples if s.get("metadata", {}).get("split") in ("dev", "test")]
    train_chunks = {c["chunk_id"] for s in train for c in s.get("contexts", [])}
    eval_chunks = {c["chunk_id"] for s in eval_splits for c in s.get("contexts", [])}
    train_docs = {c["doc_id"] for s in train for c in s.get("contexts", [])}
    eval_docs = {c["doc_id"] for s in eval_splits for c in s.get("contexts", [])}
    return {
        "chunk_overlap": sorted(train_chunks & eval_chunks),
        "doc_overlap": sorted(train_docs & eval_docs),
        "ok": not (train_chunks & eval_chunks) and not (train_docs & eval_docs),
    }
