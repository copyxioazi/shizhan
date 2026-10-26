"""时间格式化：数据库存 UTC，接口返回 +08:00。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# 固定 UTC+8，避免 Windows 环境缺少 tzdata 时启动失败
CN_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def cn_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(CN_TZ).isoformat(timespec="seconds")
