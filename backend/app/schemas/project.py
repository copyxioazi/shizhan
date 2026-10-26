from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    project_name: str = Field(min_length=1, max_length=128)
    source_type: Literal["local_path", "git_repo"] = "local_path"
    source_path: str = Field(min_length=1, max_length=1024)
    task_content: str = Field(min_length=1, max_length=5000)
    # 不传时使用系统配置 isolation.default_type；本期只接受 docker
    isolation_type: Literal["docker", "local"] | None = None


class DeleteResult(BaseModel):
    deleted: bool
    warnings: list[str] = Field(default_factory=list)
