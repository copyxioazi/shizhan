from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .io_utils import sha256_text


def _normalize(text: str) -> str:
    return "".join(ch.lower() for ch in text if ch.isalnum())


def _grams(text: str, n: int = 3) -> set[str]:
    text = _normalize(text)
    return {text[i : i + n] for i in range(max(0, len(text) - n + 1))}


def jaccard(a: str, b: str) -> float:
    ga, gb = _grams(a), _grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def deduplicate(
    samples: list[dict[str, Any]],
    *,
    max_per_chunk: int = 40,
    max_per_fact: int = 8,
    cross_split_threshold: float = 0.6,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    seen_hash: set[str] = set()
    per_chunk: Counter[str] = Counter()
    per_fact: Counter[str] = Counter()
    questions_by_split: dict[str, list[str]] = defaultdict(list)
    dropped = Counter()

    for sample in samples:
        question = sample.get("metadata", {}).get("question", "")
        qhash = sample.get("metadata", {}).get("question_hash") or sha256_text(question)
        split = sample.get("metadata", {}).get("split", "")
        if qhash in seen_hash:
            dropped["exact_question"] += 1
            continue

        evidence_ids = [e.get("chunk_id") for e in sample.get("evidence", []) if e.get("chunk_id")]
        if evidence_ids and any(per_chunk[cid] >= max_per_chunk for cid in evidence_ids):
            dropped["chunk_cap"] += 1
            continue
        fact_key = ""
        if sample.get("claims"):
            fact_key = sha256_text(sample["claims"][0].get("text", ""))
        elif sample.get("metadata", {}).get("missing_info"):
            fact_key = sha256_text("|".join(sample["metadata"]["missing_info"]))
        if evidence_ids and fact_key:
            keys = [f"{cid}:{fact_key}" for cid in evidence_ids]
            if any(per_fact[k] >= max_per_fact for k in keys):
                dropped["fact_cap"] += 1
                continue
        else:
            keys = []

        if question:
            duplicate = False
            for other_split, questions in questions_by_split.items():
                if other_split == split:
                    continue
                if any(jaccard(question, other) > cross_split_threshold for other in questions[-500:]):
                    duplicate = True
                    break
            if duplicate:
                dropped["cross_split"] += 1
                continue

        kept.append(sample)
        seen_hash.add(qhash)
        for cid in evidence_ids:
            per_chunk[cid] += 1
        for key in keys:
            per_fact[key] += 1
        questions_by_split[split].append(question)

    stats = {
        "input": len(samples),
        "kept": len(kept),
        "dropped": dict(dropped),
        "chunks_used": len(per_chunk),
    }
    return kept, stats
