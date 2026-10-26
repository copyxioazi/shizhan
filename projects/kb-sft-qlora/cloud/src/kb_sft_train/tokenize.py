from __future__ import annotations

import re
from typing import Any

THINK_RE = re.compile(r"<think\b.*?</think\s*>", re.DOTALL | re.IGNORECASE)


def assistant_text(sample: dict[str, Any]) -> str:
    return sample["messages"][2]["content"]


def has_think(text: str) -> bool:
    return bool(THINK_RE.search(text)) or "思考过程" in text


def apply_template(tokenizer, messages: list[dict[str, str]]) -> str:
    try:
        return tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
    except TypeError:
        # Older tokenizer implementations do not accept enable_thinking.
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)


def render_prompt_completion(tokenizer, sample: dict[str, Any]) -> dict[str, str]:
    prompt = apply_template(tokenizer, sample["messages"][:2])
    answer = assistant_text(sample).strip()
    eos = tokenizer.eos_token or "<|im_end|>"
    if not answer.endswith(eos):
        answer = answer + eos
    return {"prompt": prompt, "completion": answer}


def rows_to_records(rows: list[dict[str, Any]], tokenizer) -> tuple[list[dict[str, str]], list[str]]:
    records: list[dict[str, str]] = []
    skipped: list[str] = []
    for sample in rows:
        if has_think(assistant_text(sample)):
            skipped.append(sample.get("id", "?"))
            continue
        records.append(render_prompt_completion(tokenizer, sample))
    return records, skipped


def template_is_nonthinking(prompt: str) -> bool:
    """Qwen3's enable_thinking=False prompt ends with an empty think block."""
    tail = prompt[-80:]
    return "<think>" in tail and "</think>" in tail


def template_report(tokenizer, sample: dict[str, Any]) -> dict[str, Any]:
    prompt = apply_template(tokenizer, sample["messages"][:2])
    ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    return {
        "prompt_tail": prompt[-80:],
        "nonthinking_suffix": template_is_nonthinking(prompt),
        "prompt_tokens": len(ids),
        "assistant_has_think": has_think(assistant_text(sample)),
    }
