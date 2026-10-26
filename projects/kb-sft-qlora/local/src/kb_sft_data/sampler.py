from __future__ import annotations

import random
from collections import defaultdict
from typing import Any

from .config import DataConfig
from .io_utils import sha256_text

ABSENT_TOPICS = [
    "设备是否支持蓝牙配对",
    "设备能否通过手机 App 远程控制",
    "设备是否支持太阳能供电",
    "海外上门安装的收费标准",
    "是否提供以旧换新服务",
    "是否可以借用备用机",
    "设备租赁的月租价格",
    "二手设备回收的折价标准",
]

CONFLICT_PAIRS: dict[str, tuple[str, str, str]] = {
    # split -> (doc_a, doc_b, conflicting fact)
    "train": ("warranty_2024", "warranty_2025", "保修期限"),
    "dev": ("aftersales_policy", "return_sop", "退换货期限"),
    "test": ("ct320_safety", "warranty_2026", "保修期限"),
}

PRODUCT_DOC_TYPES = {"safety_manual", "safety", "operation", "consumable", "maintenance", "troubleshooting", "calibration", "user_manual"}
TERM_DOC_TYPES = {"terminology", "operation", "troubleshooting", "policy", "sop"}


def _pick(rng: random.Random, pool: list[dict[str, Any]]) -> dict[str, Any]:
    return rng.choice(pool)


def _bundle(
    *,
    split: str,
    task_type: str,
    subtype: str,
    evidence: list[dict[str, Any]],
    expected_behavior: str,
    rng: random.Random,
    topic: str = "",
    missing_topic: str = "",
    conflict_values: list[str] | None = None,
    product_model: str = "",
    item_names: list[str] | None = None,
) -> dict[str, Any]:
    labels = {f"C{i}": chunk["chunk_id"] for i, chunk in enumerate(evidence, 1)}
    raw = f"{split}|{task_type}|{subtype}|{','.join(labels.values())}|{rng.random()}"
    return {
        "bundle_id": sha256_text(raw)[:16],
        "split": split,
        "task_type": task_type,
        "subtype": subtype,
        "evidence_chunk_ids": [c["chunk_id"] for c in evidence],
        "evidence_labels": labels,
        "expected_behavior": expected_behavior,
        "topic": topic,
        "missing_topic": missing_topic,
        "conflict_values": conflict_values or [],
        "product_model": product_model,
        "item_names": item_names or [c.get("item_name", "") for c in evidence],
    }


def _conflict_bundle(
    split: str,
    chunks: list[dict[str, Any]],
    rng: random.Random,
    task_type: str = "refusal",
) -> dict[str, Any] | None:
    pair = CONFLICT_PAIRS.get(split)
    if not pair:
        return None
    doc_a, doc_b, fact = pair
    a = next((c for c in chunks if c["doc_id"] == doc_a), None)
    b = next((c for c in chunks if c["doc_id"] == doc_b), None)
    if not a or not b:
        return None
    # Prefer chunks that actually contain the conflicting section.
    a_pref = next((c for c in chunks if c["doc_id"] == doc_a and ("保修" in c["content"] or "退货" in c["content"] or "退换" in c["content"])), a)
    b_pref = next((c for c in chunks if c["doc_id"] == doc_b and ("保修" in c["content"] or "退货" in c["content"] or "退换" in c["content"])), b)
    return _bundle(
        split=split,
        task_type=task_type,
        subtype="conflict",
        evidence=[a_pref, b_pref],
        expected_behavior="conflict",
        rng=rng,
        topic=f"关于{fact}的两种说法",
        conflict_values=[],
        product_model=a_pref.get("product_model", ""),
        item_names=[a_pref.get("item_name", ""), b_pref.get("item_name", "")],
    )


def build_bundles(
    chunks: list[dict[str, Any]],
    config: DataConfig,
    split: str,
    task_type: str,
    count: int,
    rng: random.Random,
) -> list[dict[str, Any]]:
    pool = [c for c in chunks if c.get("split") == split]
    product_pool = [c for c in pool if c.get("doc_type") in PRODUCT_DOC_TYPES]
    term_pool = [c for c in pool if c.get("doc_type") in TERM_DOC_TYPES]
    if not pool:
        return []

    bundles: list[dict[str, Any]] = []
    for i in range(count):
        if task_type == "faithful":
            chunk = _pick(rng, product_pool or pool)
            subtype = "number_policy" if any(ch.isdigit() for ch in chunk["content"]) else "single_fact"
            bundles.append(
                _bundle(
                    split=split, task_type="faithful", subtype=subtype,
                    evidence=[chunk], expected_behavior="answer", rng=rng,
                    product_model=chunk.get("product_model", ""),
                    item_names=[chunk.get("item_name", "")],
                )
            )
        elif task_type == "multi":
            candidates = [c for c in pool if c.get("doc_type") in PRODUCT_DOC_TYPES] or pool
            a = _pick(rng, candidates)
            others = [c for c in candidates if c["doc_id"] != a["doc_id"]]
            b = _pick(rng, others) if others else _pick(rng, candidates)
            subtype = "cross_doc" if a["doc_id"] != b["doc_id"] else "cross_section"
            bundles.append(
                _bundle(
                    split=split, task_type="multi", subtype=subtype,
                    evidence=[a, b], expected_behavior="answer", rng=rng,
                    product_model=a.get("product_model", ""),
                    item_names=[a.get("item_name", ""), b.get("item_name", "")],
                )
            )
        elif task_type == "term":
            chunk = _pick(rng, term_pool or pool)
            subtype = {
                "terminology": "terminology",
                "operation": "steps",
                "troubleshooting": "troubleshooting",
                "policy": "policy",
                "sop": "policy",
            }.get(chunk.get("doc_type"), "terminology")
            bundles.append(
                _bundle(
                    split=split, task_type="term", subtype=subtype,
                    evidence=[chunk], expected_behavior="answer", rng=rng,
                    product_model=chunk.get("product_model", ""),
                    item_names=[chunk.get("item_name", "")],
                )
            )
        elif task_type == "refusal":
            bucket = i % 10
            if bucket < 4:
                bundles.append(
                    _bundle(
                        split=split, task_type="refusal", subtype="no_evidence",
                        evidence=[], expected_behavior="refuse", rng=rng,
                        topic=rng.choice(ABSENT_TOPICS),
                    )
                )
            elif bucket < 7:
                chunk = _pick(rng, product_pool or pool)
                bundles.append(
                    _bundle(
                        split=split, task_type="refusal", subtype="partial",
                        evidence=[chunk], expected_behavior="partial", rng=rng,
                        topic="部分可回答的问题",
                        missing_topic=rng.choice(ABSENT_TOPICS),
                        product_model=chunk.get("product_model", ""),
                        item_names=[chunk.get("item_name", "")],
                    )
                )
            else:
                conflict = _conflict_bundle(split, pool, rng)
                if conflict:
                    bundles.append(conflict)
                else:
                    chunk = _pick(rng, product_pool or pool)
                    bundles.append(
                        _bundle(
                            split=split, task_type="refusal", subtype="partial",
                            evidence=[chunk], expected_behavior="partial", rng=rng,
                            missing_topic=rng.choice(ABSENT_TOPICS),
                            product_model=chunk.get("product_model", ""),
                            item_names=[chunk.get("item_name", "")],
                        )
                    )
    return bundles


def build_all_bundles(
    chunks: list[dict[str, Any]],
    config: DataConfig,
    *,
    oversample: float = 1.6,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    rng = random.Random(seed if seed is not None else config.seed)
    all_bundles: list[dict[str, Any]] = []
    for split, targets in config.generation.target_counts.items():
        for task_type, target in targets.items():
            all_bundles.extend(
                build_bundles(
                    chunks, config, split, task_type,
                    count=max(1, int(target * oversample)), rng=rng,
                )
            )
    return all_bundles
