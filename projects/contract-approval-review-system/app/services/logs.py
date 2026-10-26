"""任务日志写入。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.db import transaction


def log_task(
    task_id: int | None,
    log_level: str,
    log_type: str,
    log_content: str,
    stage: str | None = None,
    detail: Any | None = None,
) -> None:
    """写入 task_logs；task_id 为空表示拉取级错误。"""
    now = datetime.now(timezone.utc).isoformat()
    detail_json = (
        json.dumps(detail, ensure_ascii=False) if detail is not None else None
    )
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO task_logs
                (task_id, log_level, log_type, log_content, created_at, stage, detail_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, log_level, log_type, log_content, now, stage, detail_json),
        )
