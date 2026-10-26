from __future__ import annotations

import asyncio
import json
import random
import re
from typing import Any

from .config import api_settings


class BudgetExceeded(RuntimeError):
    pass


class LLMError(RuntimeError):
    pass


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise LLMError(f"response is not JSON: {text[:300]}")


class AsyncLLMClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        generator_model: str | None = None,
        judge_model: str | None = None,
        budget_usd: float | None = None,
        timeout_s: int = 120,
        max_retries: int = 5,
    ):
        settings = api_settings()
        self.api_key = api_key or settings["api_key"]
        if not self.api_key:
            raise LLMError("DEEPSEEK_API_KEY is not set. Fill .env or run with --offline.")
        self.base_url = base_url or settings["base_url"]
        self.generator_model = generator_model or settings["generator_model"]
        self.judge_model = judge_model or settings["judge_model"]
        self.budget_usd = float(budget_usd if budget_usd is not None else settings["budget_usd"])
        self.price_in = settings["price_input_per_m"]
        self.price_out = settings["price_output_per_m"]
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.spent_usd = 0.0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self._lock = asyncio.Lock()
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout_s)
        return self._client

    async def chat_json(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 3000,
        json_mode: bool = True,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                kwargs: dict[str, Any] = {
                    "model": model or self.generator_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "max_tokens": max_tokens,
                }
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                if temperature is not None:
                    kwargs["temperature"] = temperature
                response = await self.client.chat.completions.create(**kwargs)
                await self._account(response)
                content = response.choices[0].message.content or ""
                return _extract_json(content)
            except BudgetExceeded:
                raise
            except Exception as exc:  # network, 429, schema, JSON parse
                last_error = exc
                # Some DeepSeek variants reject response_format/temperature.
                if json_mode and attempt == 0:
                    json_mode = False
                await asyncio.sleep(min(2**attempt, 30) + random.random())
        raise LLMError(f"LLM call failed after {self.max_retries} retries: {last_error}")

    async def chat_text(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1500,
    ) -> str:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = await self.client.chat.completions.create(
                    model=model or self.judge_model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                await self._account(response)
                return response.choices[0].message.content or ""
            except BudgetExceeded:
                raise
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(min(2**attempt, 30) + random.random())
        raise LLMError(f"LLM call failed after {self.max_retries} retries: {last_error}")

    async def _account(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
        cost = prompt / 1_000_000 * self.price_in + completion / 1_000_000 * self.price_out
        async with self._lock:
            self.prompt_tokens += prompt
            self.completion_tokens += completion
            self.spent_usd += cost
            if self.spent_usd > self.budget_usd:
                raise BudgetExceeded(
                    f"data budget exceeded: ${self.spent_usd:.2f} > ${self.budget_usd:.2f}"
                )

    def stats(self) -> dict[str, Any]:
        return {
            "spent_usd": round(self.spent_usd, 4),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "generator_model": self.generator_model,
            "judge_model": self.judge_model,
        }
