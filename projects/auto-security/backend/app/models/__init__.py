"""SQLAlchemy 模型。

数据库 DDL 的唯一事实来源是 ``db/init.sql``；模型仅用于查询与写入映射。
表达式唯一索引（lower(username)、md5 去重）在 init.sql 中创建。
"""

from app.models.base import Base
from app.models.project import Project
from app.models.result import AttackPath, AttackPathItem, Report, Vulnerability
from app.models.runtime import (
    ChatMessage,
    ResourceUsage,
    RuntimeLog,
    RuntimeStage,
    WorkerTask,
)
from app.models.system import IsolationEnv, SystemConfig
from app.models.user import User

__all__ = [
    "Base",
    "User",
    "Project",
    "RuntimeStage",
    "WorkerTask",
    "Vulnerability",
    "AttackPath",
    "AttackPathItem",
    "ChatMessage",
    "RuntimeLog",
    "ResourceUsage",
    "Report",
    "SystemConfig",
    "IsolationEnv",
]
