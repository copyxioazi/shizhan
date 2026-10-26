from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import EvalConfig
from .schema import load_split
from .tokenize import apply_template


def _load_causal_lm(path: str, dtype, **kwargs):
    from transformers import AutoModelForCausalLM

    try:
        return AutoModelForCausalLM.from_pretrained(path, dtype=dtype, **kwargs)
    except TypeError:
        return AutoModelForCausalLM.from_pretrained(path, torch_dtype=dtype, **kwargs)


def load_eval_model(cfg: EvalConfig, adapter: str | None):
    import torch
    from transformers import AutoTokenizer, BitsAndBytesConfig

    tokenizer = AutoTokenizer.from_pretrained(cfg.resolve_model(), trust_remote_code=True, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"
    capability = torch.cuda.get_device_capability(0) if torch.cuda.is_available() else (0, 0)
    dtype = torch.bfloat16 if (cfg.bf16 and capability[0] >= 8) else torch.float16
    quantization_config = None
    if cfg.load_in_4bit:
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=dtype,
            bnb_4bit_use_double_quant=True,
        )
    model = _load_causal_lm(
        cfg.resolve_model(),
        dtype,
        quantization_config=quantization_config,
        device_map={"": 0},
        attn_implementation="sdpa",
        trust_remote_code=True,
    )
    if adapter and adapter not in ("none", "base", ""):
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, adapter)
    model.eval()
    return model, tokenizer


def _strip_special(text: str, tokenizer) -> str:
    for token in (tokenizer.eos_token, "<|im_end|>", "<|endoftext|>"):
        if token:
            text = text.replace(token, "")
    return text.strip()


def run_eval(cfg: EvalConfig, adapter: str | None, output_path: str | Path) -> dict[str, Any]:
    import torch

    rows = load_split(cfg.path(cfg.test_file), split="test", limit=cfg.limit)
    model, tokenizer = load_eval_model(cfg, adapter)
    device = next(model.parameters()).device
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(output_path, "w", encoding="utf-8") as out:
        for i, sample in enumerate(rows, 1):
            prompt = apply_template(tokenizer, sample["messages"][:2])
            inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=4096).to(device)
            generate_kwargs = {
                "max_new_tokens": cfg.max_new_tokens,
                "do_sample": cfg.do_sample,
                "eos_token_id": tokenizer.eos_token_id,
                "pad_token_id": tokenizer.eos_token_id,
            }
            if cfg.do_sample:
                generate_kwargs["temperature"] = cfg.temperature
            with torch.no_grad():
                outputs = model.generate(**inputs, **generate_kwargs)
            new_tokens = outputs[0][inputs["input_ids"].shape[1] :]
            prediction = _strip_special(tokenizer.decode(new_tokens, skip_special_tokens=False), tokenizer)
            record = {
                "id": sample.get("id"),
                "task_type": sample.get("task_type"),
                "expected_behavior": sample.get("expected_behavior"),
                "question": sample.get("metadata", {}).get("question", ""),
                "gold": sample["messages"][2]["content"],
                "prediction": prediction,
                "contexts": sample.get("contexts", []),
                "evidence": sample.get("evidence", []),
                "metadata": sample.get("metadata", {}),
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1
            if i % 20 == 0:
                print(f"eval {i}/{len(rows)}", flush=True)
    return {"predictions": written, "output": str(output_path), "adapter": adapter or "base"}
