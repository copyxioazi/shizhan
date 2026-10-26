"""应用配置。

数据库与 Docker 连接参数来自仓库根目录 `.env`，不放入 system_configs。
`JWT_SECRET` 缺失或长度不足 32 时，导入配置即失败（后端拒绝启动）。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

# backend/app/core/config.py -> 仓库根目录
ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # PostgreSQL
    db_host: str = "127.0.0.1"
    db_port: int = 5433
    db_user: str = "postgres"
    db_password: str = ""
    db_name: str = "sec_eval"

    # 认证
    jwt_secret: str = ""
    jwt_expire_hours: int = 24

    # Docker over SSH
    docker_host: str = ""
    docker_ssh_key: str = ""
    vm_workspace_dir: str = "/home/eval/workspace"

    # 应用
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    log_level: str = "INFO"

    # 本机运行时目录
    runtime_logs_dir: str = "runtime_logs"
    reports_dir: str = "reports"

    @field_validator("jwt_secret")
    @classmethod
    def _validate_jwt_secret(cls, value: str) -> str:
        if not value or len(value) < 32:
            raise ValueError(
                "JWT_SECRET 缺失或长度小于 32，请先在仓库根目录 .env 中配置"
            )
        return value

    @property
    def database_url(self) -> str:
        url = URL.create(
            "postgresql+asyncpg",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )
        return url.render_as_string(hide_password=False)

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    def _resolve(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else ROOT_DIR / path

    @property
    def runtime_logs_path(self) -> Path:
        return self._resolve(self.runtime_logs_dir)

    @property
    def reports_path(self) -> Path:
        return self._resolve(self.reports_dir)

    @property
    def workspace_path(self) -> Path:
        """Windows 侧工作区（local 模式预留；docker 模式工作区在 VM）。"""
        return ROOT_DIR / "workspace"

    @property
    def sandbox_image(self) -> str:
        # 运行时以 system_configs 的 sandbox.image 为准，这里仅作兜底
        return "ase-sandbox:1.0"

    def ensure_dirs(self) -> None:
        self.runtime_logs_path.mkdir(parents=True, exist_ok=True)
        self.reports_path.mkdir(parents=True, exist_ok=True)

    @property
    def ssh_target(self) -> tuple[str, str, int] | None:
        """解析 DOCKER_HOST=ssh://user@host[:port]。"""
        if not self.docker_host.startswith("ssh://"):
            return None
        rest = self.docker_host[len("ssh://") :]
        rest = rest.rstrip("/")
        user_host, _, port_text = rest.partition(":")
        user, _, host = user_host.partition("@")
        if not host:
            host, user = user_host, ""
        try:
            port = int(port_text) if port_text else 22
        except ValueError:
            port = 22
        return (host, user or "eval", port)


settings = Settings()
