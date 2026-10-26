"""系统配置读取、校验与脱敏。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.core.errors import ApiError, ErrorCode
from app.models import SystemConfig

# 与 db/init.sql 第 17.1 节保持一致
DEFAULT_CONFIG: dict[str, Any] = {
    "isolation.default_type": "docker",
    "sandbox.image": "ase-sandbox:1.0",
    "sandbox.cpu_limit": 1.0,
    "sandbox.memory_limit_mb": 512,
    "sandbox.pids_limit": 128,
    "sandbox.network_enabled": False,
    "sandbox.command_timeout_seconds": 60,
    "sandbox.output_limit_bytes": 8192,
    "sandbox.command_allowlist": ["python", "python3"],
    "runtime.max_concurrent_projects": 2,
    "runtime.stage_timeout_minutes": 15,
    "runtime.resource_sample_seconds": 5,
    "runtime.retention_days": 30,
    "exec.max_files": 5000,
    "orchestration.engine": "fixed",
    "orchestration.analysis_mode": "one_shot",
    "orchestration.react_max_steps": 5,
    "orchestration.react_max_tokens": 8000,
    "orchestration.react_tool_output_chars": 6000,
    "orchestration.verify_max_retries": 0,
    "llm.base_url": "",
    "llm.api_key": "",
    "llm.model": "",
    "llm.timeout_seconds": 60,
    "llm.max_retries": 2,
    "llm.temperature": 0.2,
    "llm.max_tokens": 4096,
}

# key -> (类型, 最小值, 最大值)
_NUMERIC_RULES: dict[str, tuple[type, float, float]] = {
    "sandbox.cpu_limit": (float, 0.1, 8.0),
    "sandbox.memory_limit_mb": (int, 128, 8192),
    "sandbox.pids_limit": (int, 16, 4096),
    "sandbox.command_timeout_seconds": (int, 1, 600),
    "sandbox.output_limit_bytes": (int, 1024, 1048576),
    "runtime.max_concurrent_projects": (int, 1, 10),
    "runtime.stage_timeout_minutes": (int, 1, 120),
    "runtime.resource_sample_seconds": (int, 1, 60),
    "runtime.retention_days": (int, 1, 3650),
    "exec.max_files": (int, 1, 100000),
    "orchestration.react_max_steps": (int, 1, 12),
    "orchestration.react_max_tokens": (int, 1000, 60000),
    "orchestration.react_tool_output_chars": (int, 500, 20000),
    "orchestration.verify_max_retries": (int, 0, 3),
    "llm.timeout_seconds": (int, 1, 600),
    "llm.max_retries": (int, 0, 10),
    "llm.temperature": (float, 0.0, 2.0),
    "llm.max_tokens": (int, 1, 32768),
}

_STRING_RULES = {"sandbox.image", "llm.base_url", "llm.model", "llm.api_key"}


def mask_api_key(value: str) -> str:
    if not value:
        return ""
    suffix = value[-4:] if len(value) > 4 else ""
    prefix = "sk-****" if value.startswith("sk-") else "****"
    return f"{prefix}{suffix}"


def _validate_key_value(key: str, value: Any) -> Any:
    if key not in DEFAULT_CONFIG:
        raise ApiError(422, ErrorCode.CONFIG_INVALID, f"未登记的配置键：{key}")

    if key == "isolation.default_type":
        if value not in ("docker", "local"):
            raise ApiError(422, ErrorCode.CONFIG_INVALID, "isolation.default_type 取值非法")
        return value
    if key == "orchestration.engine":
        if value not in ("fixed", "langgraph"):
            raise ApiError(
                422,
                ErrorCode.CONFIG_INVALID,
                "orchestration.engine 只能是 fixed 或 langgraph",
            )
        return value
    if key == "orchestration.analysis_mode":
        if value not in ("one_shot", "react"):
            raise ApiError(
                422,
                ErrorCode.CONFIG_INVALID,
                "orchestration.analysis_mode 只能是 one_shot 或 react",
            )
        return value
    if key == "sandbox.network_enabled":
        if not isinstance(value, bool):
            raise ApiError(422, ErrorCode.CONFIG_INVALID, "sandbox.network_enabled 必须为布尔值")
        return value
    if key == "sandbox.command_allowlist":
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) and item.strip() for item in value)
        ):
            raise ApiError(422, ErrorCode.CONFIG_INVALID, "命令白名单必须为非空字符串数组")
        return value
    if key in _STRING_RULES:
        if not isinstance(value, str):
            raise ApiError(422, ErrorCode.CONFIG_INVALID, f"{key} 必须为字符串")
        return value
    if key in _NUMERIC_RULES:
        expected_type, minimum, maximum = _NUMERIC_RULES[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ApiError(422, ErrorCode.CONFIG_INVALID, f"{key} 必须为数字")
        if expected_type is int and not float(value).is_integer():
            raise ApiError(422, ErrorCode.CONFIG_INVALID, f"{key} 必须为整数")
        if not minimum <= float(value) <= maximum:
            raise ApiError(
                422,
                ErrorCode.CONFIG_INVALID,
                f"{key} 必须在 {minimum} 与 {maximum} 之间",
            )
        return expected_type(value)
    raise ApiError(422, ErrorCode.CONFIG_INVALID, f"未登记的配置键：{key}")


async def get_config_map(db: AsyncSession) -> dict[str, Any]:
    rows = (await db.execute(select(SystemConfig))).scalars().all()
    values = dict(DEFAULT_CONFIG)
    for row in rows:
        values[row.config_key] = row.config_value
    # llm.api_key 只写：读取时统一脱敏
    if "llm.api_key" in values:
        values["llm.api_key"] = mask_api_key(str(values["llm.api_key"] or ""))
    return dict(sorted(values.items()))


async def get_raw_config() -> dict[str, Any]:
    """供运行时读取的原始配置（含明文 Key，不得直接返回给客户端）。"""
    try:
        async with SessionLocal() as db:
            rows = (await db.execute(select(SystemConfig))).scalars().all()
            values = dict(DEFAULT_CONFIG)
            for row in rows:
                values[row.config_key] = row.config_value
            return values
    except Exception:
        return dict(DEFAULT_CONFIG)


async def update_config(
    db: AsyncSession, admin_id: int, updates: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(updates, dict):
        raise ApiError(422, ErrorCode.CONFIG_INVALID, "请求体必须为对象")

    rows = (
        (await db.execute(select(SystemConfig).where(SystemConfig.config_key.in_(updates.keys()))))
        .scalars()
        .all()
    )
    by_key = {row.config_key: row for row in rows}

    validated: dict[str, Any] = {}
    for key, value in updates.items():
        if key == "llm.api_key" and value is None:
            continue
        validated[key] = _validate_key_value(key, value)

    for key, value in validated.items():
        row = by_key.get(key)
        if row is None:
            row = SystemConfig(config_key=key, config_value=value)
            db.add(row)
        else:
            row.config_value = value
        row.updated_by = admin_id

    await db.commit()

    # 系统审计日志：只记录键名，不记录值
    from app.services.monitor_service import add_log

    await add_log(
        None,
        "info",
        f"系统配置更新，操作人 user_id={admin_id}，键：{', '.join(sorted(validated))}",
    )
    return await get_config_map(db)
