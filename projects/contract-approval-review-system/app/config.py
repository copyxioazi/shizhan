"""环境变量与路径配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path | None = None, override: bool = False) -> Path | None:
    """加载项目根目录 .env（无第三方依赖）。

    - 支持 KEY=VALUE、export KEY=VALUE、引号与行尾 # 注释。
    - 默认沿用 dotenv 惯例：已存在的非空环境变量优先，方便部署时覆盖。
    """
    env_path = Path(path) if path is not None else BASE_DIR / ".env"
    try:
        content = env_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None

    # 只有加载前的进程环境变量优先；.env 内部的重复键按后出现者生效。
    preexisting = set(os.environ)
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if not override and key in preexisting:
            continue
        os.environ[key] = value

    return env_path


_LOADED_ENV_FILE = _load_dotenv()


def _bool_env(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    base_dir: Path = BASE_DIR
    data_dir: Path = BASE_DIR / "data"
    sample_dir: Path = BASE_DIR / "sample_contracts"
    local_db_path: Path = Path(os.getenv("LOCAL_DB_PATH", str(BASE_DIR / "data" / "app.db")))
    mock_db_path: Path = Path(os.getenv("MOCK_DB_PATH", str(BASE_DIR / "data" / "mock_upstream.db")))
    upstream_base_url: str = os.getenv("UPSTREAM_BASE_URL", "http://127.0.0.1:8000")
    llm_enabled: bool = _bool_env("LLM_ENABLED")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "")
    llm_timeout_seconds: int = _int_env("LLM_TIMEOUT_SECONDS", 15)
    ocr_text_min_chars: int = _int_env("OCR_TEXT_MIN_CHARS", 40)
    queue_maxsize: int = _int_env("QUEUE_MAXSIZE", 100)
    worker_concurrency: int = _int_env("WORKER_CONCURRENCY", 2)
    shutdown_grace_seconds: int = _int_env("SHUTDOWN_GRACE_SECONDS", 10)


settings = Settings()
