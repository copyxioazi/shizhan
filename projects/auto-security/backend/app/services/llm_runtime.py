"""一次运行内的 LLM 模式状态与降级开关。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.llm_client import LLMClient, llm_configured


class LLMUnavailable(Exception):
    """本轮 LLM 不可用（未配置或调用失败），调用方应使用规则引擎。"""


@dataclass
class LLMRuntime:
    config: dict[str, Any]
    client: LLMClient | None
    active: bool
    reason: str
    model: str = ""
    fallback_announced: bool = False
    _token_count: int = field(default=0)

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "LLMRuntime":
        if not llm_configured(config):
            return cls(
                config=config,
                client=None,
                active=False,
                reason="未配置 LLM（base_url / model / api_key 不完整）",
            )
        return cls(
            config=config,
            client=LLMClient(config),
            active=True,
            reason="",
            model=str(config.get("llm.model", "")),
        )

    @property
    def mode(self) -> str:
        return "llm" if self.active else "mock"

    @property
    def token_count(self) -> int:
        if self.client is not None:
            return self.client.token_count
        return self._token_count

    async def call_json(self, messages: list[dict[str, str]]) -> Any:
        if not self.active or self.client is None:
            raise LLMUnavailable(self.reason or "LLM 不可用")
        try:
            return await self.client.chat_json(messages)
        except Exception as exc:  # noqa: BLE001 - 统一收敛为降级
            self.active = False
            self.reason = str(exc)
            self._token_count = self.client.token_count
            raise LLMUnavailable(str(exc)) from exc

    def disable(self, reason: str) -> None:
        self.active = False
        self.reason = reason
        if self.client is not None:
            self._token_count = self.client.token_count
