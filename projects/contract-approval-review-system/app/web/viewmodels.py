"""页面展示辅助。"""

from __future__ import annotations

import json

from app.status import TASK_STATUS_LABELS

RISK_LABELS = {"high": "高风险", "medium": "中风险", "low": "低风险"}


def risk_label(level: str | None) -> str:
    return RISK_LABELS.get(level or "", level or "未知")


def status_label(status: str | None) -> str:
    return TASK_STATUS_LABELS.get(status or "", status or "未知")


def format_position(position: dict | None) -> str:
    """把结构化位置转成人类可读文本；当前直接返回 JSON。"""
    if not position:
        return "无位置信息"
    return json.dumps(position, ensure_ascii=False)
