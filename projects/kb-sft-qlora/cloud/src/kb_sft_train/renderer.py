from __future__ import annotations

import re
from typing import Any

from .config import SHARED_DIR


def _load(name: str) -> str:
    return (SHARED_DIR / "templates" / name).read_text(encoding="utf-8").strip()


SYSTEM_PROMPT = _load("system_prompt.txt")
USER_TEMPLATE = _load("user_template.txt")


def context_block(chunks: list[dict[str, Any]]) -> str:
    parts = []
    for idx, chunk in enumerate(chunks, 1):
        parts.append(
            f"[{idx}][{chunk.get('source', 'local')}]"
            f"[{chunk.get('file_title', '')}]"
            f"[{chunk.get('url', '')}]\n{chunk.get('content', '')}\n\n"
        )
    return "".join(parts)


def user_content(chunks: list[dict[str, Any]], item_names: list[str], question: str) -> str:
    names = "、".join(n for n in item_names if n) or "无"
    return USER_TEMPLATE.format(context=context_block(chunks), item_names=names, question=question.strip())


def question_from_sample(sample: dict[str, Any]) -> str:
    question = sample.get("metadata", {}).get("question", "")
    if question:
        return question
    match = re.search(r"【用户问题】\s*\n(.*?)\n\s*请回答：", sample["messages"][1]["content"], re.DOTALL)
    return match.group(1).strip() if match else ""


def item_names_from_sample(sample: dict[str, Any]) -> list[str]:
    names = sample.get("metadata", {}).get("item_names")
    if names:
        return list(names)
    match = re.search(r"【相关实体】\s*\n(.*?)\n\s*【用户问题】", sample["messages"][1]["content"], re.DOTALL)
    if not match:
        return []
    return [n for n in re.split(r"[、,，]", match.group(1).strip()) if n and n != "无"]


def build_user_from_sample(sample: dict[str, Any]) -> str:
    return user_content(
        sample.get("contexts", []),
        item_names_from_sample(sample),
        question_from_sample(sample),
    )


def assert_user_isomorphic(sample: dict[str, Any]) -> list[str]:
    rebuilt = build_user_from_sample(sample)
    stored = sample["messages"][1]["content"]
    if rebuilt == stored:
        return []
    # Give a compact diff hint.
    for i, (a, b) in enumerate(zip(rebuilt, stored)):
        if a != b:
            return [f"user message diverges at char {i}: rebuilt={rebuilt[i:i+40]!r} stored={stored[i:i+40]!r}"]
    return [f"user message length differs: rebuilt={len(rebuilt)} stored={len(stored)}"]
