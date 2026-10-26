"""日志配置与敏感信息脱敏。"""

from __future__ import annotations

import logging
import re

from app.core.config import settings

_SK_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}\b")
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b")
_SECRET_FIELD_PATTERN = re.compile(
    r'("(?:(?:password|api_key|token|secret)[^"]*)"\s*:\s*")([^"]*)(")',
    re.IGNORECASE,
)
_PASSWORD_KV_PATTERN = re.compile(
    r"\b(password|api_key|token|secret)\s*[=:]\s*['\"]?([^\s'\"，,]+)",
    re.IGNORECASE,
)


def sanitize(text: str) -> str:
    if not text:
        return text
    text = _SK_PATTERN.sub("sk-******", text)
    text = _JWT_PATTERN.sub("******", text)
    text = _SECRET_FIELD_PATTERN.sub(r"\1******\3", text)
    text = _PASSWORD_KV_PATTERN.sub(r"\1=******", text)
    return text


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
