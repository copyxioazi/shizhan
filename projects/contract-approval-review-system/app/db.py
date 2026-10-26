"""SQLite 连接与脚本执行。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import settings


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """打开短连接：WAL、外键、5 秒忙等待。"""
    path = Path(db_path) if db_path is not None else settings.local_db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def transaction(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def executescript_file(conn: sqlite3.Connection, path: Path) -> None:
    conn.executescript(Path(path).read_text(encoding="utf-8"))


def table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {row[0] for row in rows}
