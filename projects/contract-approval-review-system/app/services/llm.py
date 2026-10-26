"""可选的 OpenAI 兼容润色。

默认关闭；开启后只发送派生摘要/命中项，不发送合同全文。
任何异常都回退模板，不影响审查主流程。
"""

from __future__ import annotations

import json

from app.config import settings
from app.services.logs import log_task


def _fallback(summary_text: str, focus_points: list[str], reason: str | None = None) -> dict:
    if reason:
        try:
            log_task(None, "WARN", "LLM_FALLBACK", f"LLM 润色失败，已回退模板：{reason}")
        except Exception:  # noqa: BLE001 - 日志失败不能影响审查
            pass
    return {
        "summary_text": summary_text,
        "focus_points": focus_points,
        "llm_enhanced": False,
    }


def polish_review(
    summary_text: str, focus_points: list[str], hits: list[dict]
) -> dict:
    """返回 {summary_text, focus_points, llm_enhanced}；失败时调用方回退模板。"""
    if not settings.llm_enabled:
        return _fallback(summary_text, focus_points)
    if not (settings.llm_base_url and settings.llm_model):
        return _fallback(summary_text, focus_points, "缺少 LLM_BASE_URL/LLM_MODEL")

    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    hit_items = [
        {
            "rule_name": hit.get("rule_name"),
            "risk_level": hit.get("risk_level"),
            "suggestion": hit.get("suggestion_text"),
        }
        for hit in hits
    ]
    user_payload = {
        "summary": summary_text,
        "focus_points": focus_points,
        "hits": hit_items,
    }
    prompt = (
        "你是合同审查助手。请在不改变风险结论的前提下，润色下面的中文审查摘要和关注点。"
        "只返回 JSON：{\"summary_text\": \"...\", \"focus_points\": [\"...\"]}。"
        "不要编造新风险，不要输出合同全文。\n"
        + json.dumps(user_payload, ensure_ascii=False)
    )

    try:
        import httpx

        headers = {"Content-Type": "application/json"}
        if settings.llm_api_key:
            headers["Authorization"] = f"Bearer {settings.llm_api_key}"
        body = {
            "model": settings.llm_model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": "你是严谨的中文合同审查助手，只输出 JSON。",
                },
                {"role": "user", "content": prompt},
            ],
        }
        with httpx.Client(
            timeout=settings.llm_timeout_seconds, trust_env=False
        ) as client:
            response = client.post(url, headers=headers, json=body)
            response.raise_for_status()
            payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        polished_summary = str(parsed.get("summary_text") or "").strip()
        polished_points = parsed.get("focus_points")
        if not polished_summary or not isinstance(polished_points, list):
            raise ValueError("LLM 返回结构不合法")
        polished_points = [str(item).strip() for item in polished_points if str(item).strip()]
        if not polished_points:
            polished_points = focus_points
        return {
            "summary_text": polished_summary,
            "focus_points": polished_points[:8],
            "llm_enhanced": True,
        }
    except Exception as exc:  # noqa: BLE001 - 任意失败回退模板
        return _fallback(summary_text, focus_points, str(exc))
