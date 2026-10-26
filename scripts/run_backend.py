"""启动后端服务。

参数默认取自仓库根目录 `.env` 的 APP_HOST / APP_PORT，避免在终端里硬编码端口
导致与前端 Vite 的 ASE_API_TARGET 不一致。导入 app.core.config 时会校验必填配置
（例如 JWT_SECRET 至少 32 字符），校验失败直接退出并给出提示。

用法（在仓库根目录执行）：

    backend/.venv/Scripts/python.exe scripts/run_backend.py
    backend/.venv/Scripts/python.exe scripts/run_backend.py --reload
    backend/.venv/Scripts/python.exe scripts/run_backend.py --port 8011
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"


def main() -> None:
    parser = argparse.ArgumentParser(description="启动自动化安全评估后端")
    parser.add_argument("--host", default=None, help="监听地址，默认读取 .env 的 APP_HOST")
    parser.add_argument("--port", type=int, default=None, help="监听端口，默认读取 .env 的 APP_PORT")
    parser.add_argument("--reload", action="store_true", help="开发模式：代码变更自动重载")
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help="日志级别，默认读取 .env 的 LOG_LEVEL",
    )
    args = parser.parse_args()

    # `app` 包位于 backend/ 下。切到 backend 并写入 PYTHONPATH，
    # 保证 --reload 派生出的子进程也能导入 app.main。
    os.chdir(BACKEND_DIR)
    sys.path.insert(0, str(BACKEND_DIR))
    os.environ["PYTHONPATH"] = os.pathsep.join(
        [str(BACKEND_DIR), os.environ.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)

    try:
        from app.core.config import settings
    except Exception as exc:  # noqa: BLE001 - 把配置错误直接呈现给使用者
        raise SystemExit(f"配置校验失败：{exc}") from exc

    import uvicorn

    host = args.host or settings.app_host
    port = args.port or settings.app_port
    log_level = (args.log_level or settings.log_level).lower()

    print(f"后端启动：http://{host}:{port}", flush=True)
    print(f"  OpenAPI:  http://{host}:{port}/docs", flush=True)
    print(f"  健康检查: http://{host}:{port}/healthz", flush=True)
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=args.reload,
        log_level=log_level,
    )


if __name__ == "__main__":
    main()
