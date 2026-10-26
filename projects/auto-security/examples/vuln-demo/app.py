"""vuln-demo：仅用于本地演示的漏洞样例（标准库实现）。

包含 5 类已知漏洞：
1. /search    SQL 注入
2. /ping      命令注入
3. /download  路径穿越
4. /orders    越权访问（IDOR）
5. config.py  硬编码密钥

请勿在真实环境部署。启动：python app.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from config import SECRET_KEY

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROUTES = {}
_CONN = sqlite3.connect(":memory:", check_same_thread=False)

ORDERS = {
    1001: {"order_id": 1001, "owner_id": 1, "item": "机械键盘", "amount": 399},
    1002: {"order_id": 1002, "owner_id": 2, "item": "显示器", "amount": 1299},
}


def route(path):
    def decorator(function):
        ROUTES[path] = function
        return function

    return decorator


def init_db():
    _CONN.execute("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT)")
    _CONN.executemany(
        "INSERT INTO items (name) VALUES (?)",
        [("Widget",), ("Gadget",), ("Gizmo",)],
    )
    _CONN.commit()


@route("/search")
def search_items(q):
    # 演示缺陷：外部输入直接拼接进 SQL 语句
    query = f"SELECT id, name FROM items WHERE name LIKE '%{q}%'"
    rows = _CONN.execute(query).fetchall()
    return [{"id": row[0], "name": row[1]} for row in rows]


@route("/ping")
def ping_host(host):
    # 演示缺陷：外部输入直接进入命令解释器
    output = os.popen(f"echo pinging {host}").read()
    return {"output": output.strip()}


@route("/download")
def download_file(filename):
    # 演示缺陷：拼接后的路径未做规范化与根目录校验
    path = os.path.join(BASE_DIR, "uploads", filename)
    with open(path, "rb") as handle:
        return handle.read()


@route("/orders")
def get_order(order_id):
    # 演示缺陷：按对象 ID 查询订单，未校验订单归属
    return ORDERS.get(int(order_id))


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "VulnDemo/1.0"

    def do_GET(self):  # noqa: N802 - 标准库约定
        parsed = urlparse(self.path)
        handler = ROUTES.get(parsed.path)
        if handler is None:
            self.send_response(404)
            self.end_headers()
            return

        params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        try:
            result = handler(**params)
        except Exception as exc:  # noqa: BLE001 - 演示用简化错误处理
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
            )
            return

        if isinstance(result, bytes):
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            self.wfile.write(result)
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            json.dumps(result, ensure_ascii=False).encode("utf-8")
        )

    def log_message(self, fmt, *args):  # noqa: A003
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


init_db()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"vuln-demo listening on http://127.0.0.1:{port} (secret={SECRET_KEY[:3]}...)")
    ThreadingHTTPServer(("127.0.0.1", port), DemoHandler).serve_forever()
