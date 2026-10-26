from __future__ import annotations

import os
from pathlib import Path

import pytest

from kb_sft_train.config import CLOUD_DIR
from kb_sft_train.renderer import assert_user_isomorphic
from kb_sft_train.schema import load_split
from kb_sft_train.tokenize import has_think, render_prompt_completion, template_is_nonthinking

ALL = CLOUD_DIR / "data" / "kb_sft_all.jsonl"


def _samples(limit: int = 5):
    if not ALL.exists():
        pytest.skip("cloud/data/kb_sft_all.jsonl not found")
    return load_split(ALL, split="dev", limit=limit)


def test_user_message_isomorphic():
    for sample in _samples():
        errors = assert_user_isomorphic(sample)
        assert not errors, f"{sample.get('id')}: {errors}"


def test_assistant_has_no_think():
    for sample in _samples():
        assert not has_think(sample["messages"][2]["content"]), sample.get("id")


def test_qwen3_nonthinking_template():
    transformers = pytest.importorskip("transformers")
    model = os.getenv("QWEN3_TOKENIZER", "Qwen/Qwen3-8B")
    try:
        tokenizer = transformers.AutoTokenizer.from_pretrained(model, trust_remote_code=True)
    except Exception as exc:  # offline test machines
        pytest.skip(f"tokenizer unavailable: {exc}")
    sample = _samples(1)[0]
    prompt = tokenizer.apply_chat_template(
        sample["messages"][:2], tokenize=False, add_generation_prompt=True, enable_thinking=False
    )
    assert template_is_nonthinking(prompt), prompt[-120:]
    record = render_prompt_completion(tokenizer, sample)
    assert record["prompt"] == prompt
    assert record["completion"].endswith(tokenizer.eos_token or "<|im_end|>")
