"""通用处理角色：分析计划与上下文汇总。"""

from __future__ import annotations

from app.services.llm_runtime import LLMUnavailable
from app.services.monitor_service import add_chat, add_log
from app.workers.base import WorkerContext
from app.workers.llm_prompts import (
    LLMValidationError,
    general_messages,
    parse_general_plan,
)
from app.workers.llm_support import announce_fallback, announce_llm_output_invalid

FOCUS_KEYWORDS = {
    "数据库访问": ["sql", "execute", "select", "sqlite", "cursor"],
    "命令执行": ["os.system", "os.popen", "subprocess", "shell=True"],
    "文件操作": ["open(", "os.path", "send_file", "download"],
    "权限校验": ["order", "profile", "user_id", "owner", "permission"],
    "凭据管理": ["secret", "password", "api_key", "token"],
}


async def run_general(ctx: WorkerContext) -> dict:
    plan: dict | None = None
    if ctx.llm.active:
        try:
            data = await ctx.llm.call_json(general_messages(ctx.task_content))
            plan = parse_general_plan(data)
            await add_log(
                ctx.project_id,
                "info",
                f"LLM 生成分析计划（model={ctx.llm.model}）",
                stage_id=ctx.stage_id,
                worker_task_id=ctx.worker_task_id,
            )
        except LLMUnavailable as exc:
            await announce_fallback(ctx, str(exc))
        except LLMValidationError as exc:
            await announce_llm_output_invalid(ctx, str(exc))

    if plan is None:
        lowered = ctx.task_content.lower()
        focus_areas = [
            area
            for area, keywords in FOCUS_KEYWORDS.items()
            if any(keyword.lower() in lowered for keyword in keywords)
        ] or list(FOCUS_KEYWORDS.keys())
        plan = {
            "focus_areas": focus_areas,
            "file_globs": ["**/*.py"],
            "keywords": [
                "execute",
                "os.system",
                "subprocess",
                "open(",
                "SECRET_KEY",
                "order_id",
            ],
            "risk_hypotheses": [
                "存在 SQL 语句拼接",
                "存在命令注入",
                "存在路径穿越",
                "存在越权访问",
            ],
        }

    focus_areas = plan.get("focus_areas") or []
    await add_log(
        ctx.project_id,
        "info",
        f"通用角色生成分析计划，关注范围：{'、'.join(focus_areas)}",
        stage_id=ctx.stage_id,
        worker_task_id=ctx.worker_task_id,
    )
    await add_chat(
        ctx.project_id,
        "general",
        "thought",
        f"分析计划：围绕 {'、'.join(focus_areas)} 展开，优先检查外部输入进入 SQL、命令、文件与对象访问的路径。",
    )
    return plan
