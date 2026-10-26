from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    """临时双库 + 真实 uvicorn 回环，供集成/E2E 测试复用。"""
    from app.config import settings

    tmp = tmp_path_factory.mktemp("live_server")
    original = (
        settings.local_db_path,
        settings.mock_db_path,
        settings.data_dir,
    )
    object.__setattr__(settings, "local_db_path", tmp / "app.db")
    object.__setattr__(settings, "mock_db_path", tmp / "mock_upstream.db")
    object.__setattr__(settings, "data_dir", tmp / "data")

    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from init_db import init_databases

    init_databases(
        reset=True, seed_rule_data=True, seed_mock=True, generate=True
    )

    import uvicorn

    from app.main import app
    from app.services.upstream_client import UpstreamClient, set_upstream_client

    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, log_level="warning", lifespan="on"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 20
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("测试服务启动超时")

    port = server.servers[0].sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    set_upstream_client(UpstreamClient(base_url=base_url))

    import httpx

    client = httpx.Client(base_url=base_url, timeout=120.0, trust_env=False)
    try:
        yield client
    finally:
        client.close()
        set_upstream_client(None)
        server.should_exit = True
        thread.join(timeout=10)
        object.__setattr__(settings, "local_db_path", original[0])
        object.__setattr__(settings, "mock_db_path", original[1])
        object.__setattr__(settings, "data_dir", original[2])
