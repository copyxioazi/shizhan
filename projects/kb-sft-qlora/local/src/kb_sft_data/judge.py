from __future__ import annotations

import asyncio
from typing import Any

from .llm_client import AsyncLLMClient
from .templates import CITATION_HEADER

JUDGE_SYSTEM = "你是严格的知识库问答数据质检员。只根据参考内容判断答案，不要使用外部知识。只输出 JSON。"


def _context_text(contexts: list[dict[str, Any]]) -> str:
    parts = []
    for chunk in contexts:
        parts.append(
            f"[{chunk.get('idx')}] {chunk.get('file_title', '')} | "
            f"{chunk.get('display_title') or chunk.get('title', '')}\n{chunk.get('content', '')}\n"
        )
    return "\n".join(parts)


def _threshold(sample: dict[str, Any], scores: dict[str, Any]) -> bool:
    behavior = sample.get("expected_behavior")
    if behavior == "refuse":
        return bool(scores.get("refusal_correct")) and int(scores.get("missing_info_quality", 0)) >= 4
    if behavior == "conflict":
        return bool(scores.get("conflict_neutral")) and bool(scores.get("conflict_both_sides"))
    if behavior == "partial":
        return (
            int(scores.get("faithfulness", 0)) >= 5
            and int(scores.get("citation_correctness", 0)) >= 5
            and int(scores.get("completeness", 0)) >= 4
        )
    ok = (
        int(scores.get("faithfulness", 0)) >= 5
        and int(scores.get("citation_correctness", 0)) >= 5
        and int(scores.get("completeness", 0)) >= 4
        and int(scores.get("format", 0)) >= 4
    )
    if sample.get("task_type") == "multi":
        ok = ok and int(scores.get("completeness", 0)) >= 4
    return ok


async def judge_sample(sample: dict[str, Any], client: AsyncLLMClient, prompt_template: str) -> dict[str, Any]:
    question = sample.get("metadata", {}).get("question", "")
    answer = sample["messages"][2]["content"]
    user = (
        prompt_template.replace("{context}", _context_text(sample.get("contexts", [])))
        .replace("{question}", question)
        .replace("{answer}", answer)
    )
    result = await client.chat_json(
        JUDGE_SYSTEM, user, model=client.judge_model, temperature=0, max_tokens=1200, json_mode=True
    )
    result["accept"] = _threshold(sample, result)
    return result


async def judge_batch(
    samples: list[dict[str, Any]],
    client: AsyncLLMClient,
    prompt_template: str,
    *,
    concurrency: int = 8,
) -> list[dict[str, Any]]:
    sem = asyncio.Semaphore(concurrency)

    async def one(sample: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            try:
                verdict = await judge_sample(sample, client, prompt_template)
                return {"id": sample["id"], "verdict": verdict, "error": None}
            except Exception as exc:
                return {"id": sample["id"], "verdict": None, "error": str(exc)}

    return await asyncio.gather(*(one(s) for s in samples))
