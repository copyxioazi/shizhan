"""OpenAI 兼容 LLM 客户端。

- 调用 ``{base_url}/chat/completions``；
- 超时、重试与 JSON 解析；
- 累计 token 用量（供资源采样）；
- 只负责传输与 JSON 解析，角色 Schema 校验在 ``workers.llm_prompts``。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx


class LLMRequestError(Exception):
    """网络、HTTP 状态或响应结构错误。"""


@dataclass
class LLMResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


def llm_configured(config: dict[str, Any]) -> bool:
    return bool(
        config.get("llm.base_url")
        and config.get("llm.api_key")
        and config.get("llm.model")
    )


def strip_code_fences(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


class LLMClient:
    def __init__(self, config: dict[str, Any]) -> None:
        self.base_url = str(config.get("llm.base_url", "")).rstrip("/")
        self.api_key = str(config.get("llm.api_key", ""))
        self.model = str(config.get("llm.model", ""))
        self.timeout = float(config.get("llm.timeout_seconds", 60))
        self.max_retries = int(config.get("llm.max_retries", 2))
        self.temperature = float(config.get("llm.temperature", 0.2))
        self.max_tokens = int(config.get("llm.max_tokens", 4096))
        self.token_count = 0

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def _trust_env(self) -> bool:
        # 本机 mock / 本地服务不走系统代理；外部地址允许使用环境代理
        host = (urlparse(self.base_url).hostname or "").lower()
        return host not in {"127.0.0.1", "localhost", "::1"}

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> LLMResult:
        if not self.configured:
            raise LLMRequestError("LLM 未配置")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for _ in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout, trust_env=self._trust_env()
                ) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                if response.status_code in (401, 403, 429) or response.status_code >= 500:
                    raise LLMRequestError(
                        f"LLM 返回 HTTP {response.status_code}: {response.text[:200]}"
                    )
                response.raise_for_status()
                body = response.json()
                message = body["choices"][0]["message"]
                content = message.get("content")
                if content is None:
                    content = ""
                if not isinstance(content, str):
                    raise LLMRequestError("LLM 响应 content 不是字符串")
                tool_calls = message.get("tool_calls") or []
                if not isinstance(tool_calls, list):
                    raise LLMRequestError("LLM 响应 tool_calls 不是数组")
                usage = body.get("usage", {})
                prompt_tokens = int(usage.get("prompt_tokens", 0))
                completion_tokens = int(usage.get("completion_tokens", 0))
                self.token_count += prompt_tokens + completion_tokens
                return LLMResult(
                    content, prompt_tokens, completion_tokens, tool_calls
                )
            except (httpx.HTTPError, LLMRequestError, KeyError, IndexError, ValueError) as exc:
                last_error = exc
        raise LLMRequestError(f"LLM 调用失败（已重试 {self.max_retries} 次）：{last_error}") from last_error

    async def chat_json(self, messages: list[dict[str, str]]) -> Any:
        result = await self.chat(messages)
        text = strip_code_fences(result.content)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMRequestError("LLM 输出不是合法 JSON") from exc
