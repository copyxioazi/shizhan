from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Any

from .config import LOCAL_DIR, DataConfig
from .renderer import build_sample
from .retriever import HybridRetriever

PROMPT_DIR = LOCAL_DIR / "prompts"


def load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def fill(template: str, mapping: dict[str, str]) -> str:
    for key, value in mapping.items():
        template = template.replace("{" + key + "}", str(value))
    return template


def evidence_block(bundle: dict[str, Any], chunks_by_id: dict[str, dict[str, Any]]) -> str:
    lines: list[str] = []
    for label, chunk_id in bundle.get("evidence_labels", {}).items():
        chunk = chunks_by_id[chunk_id]
        title = chunk.get("display_title") or chunk.get("title", "")
        lines.append(f"[{label}] {chunk.get('file_title', '')} | {title}\n{chunk.get('content', '')}\n")
    return "\n".join(lines) or "(无证据片段)"


def generation_prompt(
    bundle: dict[str, Any],
    chunks_by_id: dict[str, dict[str, Any]],
    n_candidates: int,
) -> tuple[str, str]:
    behavior = bundle["expected_behavior"]
    if behavior == "refuse":
        template = load_prompt("qa_refusal.md")
    elif behavior == "partial" or behavior == "conflict":
        template = load_prompt("qa_refusal.md")
    elif bundle["task_type"] == "multi":
        template = load_prompt("qa_multi.md")
    elif bundle["task_type"] == "term":
        template = load_prompt("qa_term.md")
    else:
        template = load_prompt("qa_faithful.md")
    mode = {"refuse": "no_evidence", "answer": "faithful"}.get(behavior, behavior)
    user = fill(
        template,
        {
            "n": n_candidates,
            "mode": mode,
            "topic": bundle.get("topic", ""),
            "missing_topic": bundle.get("missing_topic", ""),
            "evidence": evidence_block(bundle, chunks_by_id),
        },
    )
    system = "你是知识库问答数据构造专家。只输出合法 JSON，不要输出解释。"
    return system, user


def _first_sentence(text: str, limit: int = 140) -> str:
    # Drop the markdown heading line, keep the body.
    lines = [line for line in text.strip().splitlines() if not line.strip().startswith("#")]
    text = "\n".join(lines).strip() or text.strip()
    parts = re.split(r"(?<=[。！？；])", text)
    sentence = next((p.strip() for p in parts if p.strip()), text.strip())
    return sentence[:limit]


def _claim(text: str, label: str, idx: int = 1) -> dict[str, Any]:
    return {"claim_id": f"c{idx}", "text": text, "evidence_labels": [label]}


def offline_candidates(
    bundle: dict[str, Any],
    chunks_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Deterministic candidates for smoke tests when no API key is available."""
    labels = list(bundle.get("evidence_labels", {}).keys())
    chunks = [chunks_by_id[bundle["evidence_labels"][label]] for label in labels]
    behavior = bundle["expected_behavior"]

    if behavior == "refuse":
        topic = bundle.get("topic") or "该主题"
        return [
            {
                "question": f"{topic}？",
                "hyde_text": "资料中没有相关说明。",
                "answer_text": "无法根据现有资料回答该问题。\n\n缺少以下信息：\n1. 相关资料未收录该主题。\n2. 需要向设备厂商或售后确认。",
                "claims": [],
                "missing_info": ["相关资料未收录该主题", "需要向设备厂商或售后确认"],
                "conflict_values": [],
                "format_template": "plain",
                "difficulty": "easy",
            }
        ]
    if behavior == "partial":
        first = _first_sentence(chunks[0]["content"])
        missing = bundle.get("missing_topic") or "该信息"
        return [
            {
                "question": f"{chunks[0].get('display_title') or chunks[0]['file_title']}有什么要求？另外，{missing}如何办理？",
                "hyde_text": first,
                "answer_text": f"{first}[C1]\n\n【无法确认的部分】\n1. {missing}：资料中未提及。",
                "claims": [_claim(first, "C1")],
                "missing_info": [f"{missing}：资料中未提及"],
                "conflict_values": [],
                "format_template": "plain",
                "difficulty": "medium",
            }
        ]
    if behavior == "conflict":
        a = _first_sentence(chunks[0]["content"])
        b = _first_sentence(chunks[1]["content"])
        return [
            {
                "question": f"关于{bundle.get('topic') or '该事项'}，资料里是怎么规定的？",
                "hyde_text": f"{a}；{b}",
                "answer_text": f"关于该事项，现有资料存在两种说法：\n- 说法一：{a}[C1]\n- 说法二：{b}[C2]\n两处资料未说明适用条件，无法判断哪一种适用于您的情况。",
                "claims": [_claim(a, "C1", 1), _claim(b, "C2", 2)],
                "missing_info": [],
                "conflict_values": ["说法一", "说法二"],
                "format_template": "policy",
                "difficulty": "hard",
            }
        ]

    if bundle["task_type"] == "multi":
        a = _first_sentence(chunks[0]["content"])
        b = _first_sentence(chunks[1]["content"])
        return [
            {
                "question": f"{chunks[0].get('display_title') or chunks[0]['file_title']}和{chunks[1].get('display_title') or chunks[1]['file_title']}分别有什么要求？",
                "hyde_text": f"{a}；{b}",
                "answer_text": f"{a}[C1]\n\n{b}[C2]",
                "claims": [_claim(a, "C1", 1), _claim(b, "C2", 2)],
                "missing_info": [],
                "conflict_values": [],
                "format_template": "plain",
                "difficulty": "medium",
            }
        ]

    first = _first_sentence(chunks[0]["content"])
    if bundle["task_type"] == "term" and bundle.get("subtype") == "steps":
        question = f"请说明{chunks[0].get('display_title') or chunks[0]['file_title']}的操作步骤。"
        template = "steps"
    elif bundle["task_type"] == "term" and bundle.get("subtype") == "troubleshooting":
        question = f"{chunks[0].get('display_title') or chunks[0]['file_title']}出现异常时怎么处理？"
        template = "troubleshooting"
    elif bundle["task_type"] == "term" and bundle.get("subtype") == "policy":
        question = f"{chunks[0].get('display_title') or chunks[0]['file_title']}是怎么规定的？"
        template = "policy"
    else:
        question = f"{chunks[0].get('display_title') or chunks[0]['file_title']}有什么要求？"
        template = "plain"
    return [
        {
            "question": question,
            "hyde_text": first,
            "answer_text": f"{first}[C1]",
            "claims": [_claim(first, "C1")],
            "missing_info": [],
            "conflict_values": [],
            "format_template": template,
            "difficulty": "easy",
        }
    ]


def make_sample(
    bundle: dict[str, Any],
    candidate: dict[str, Any],
    retriever: HybridRetriever,
    config: DataConfig,
    rng: random.Random,
    *,
    generator_model: str = "",
) -> dict[str, Any]:
    behavior = bundle["expected_behavior"]
    entity_filter = behavior in ("answer", "partial") and bundle["task_type"] in ("faithful", "term", "refusal")
    contexts = retriever.retrieve(
        candidate["question"],
        candidate.get("hyde_text", ""),
        bundle.get("evidence_chunk_ids", []),
        bundle["split"],
        bundle.get("product_model", ""),
        rng,
        entity_filter=entity_filter,
        distractor_rate=0.30,
    )
    return build_sample(
        candidate,
        bundle,
        contexts,
        generator_model=generator_model,
        prompt_version="qa-v1",
    )
