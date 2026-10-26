-- Mock 上游库：data/mock_upstream.db（与本地库物理隔离）
-- 由 scripts/init_db.py 单独执行；绝不要执行到 data/app.db。

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS upstream_approvals (
    approval_code   TEXT PRIMARY KEY,
    approval_title  TEXT NOT NULL,
    applicant_name  TEXT NOT NULL,
    applied_at      TEXT NOT NULL,
    form_data_json  TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS upstream_attachments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    approval_code   TEXT NOT NULL REFERENCES upstream_approvals(approval_code) ON DELETE CASCADE,
    file_name       TEXT NOT NULL,
    file_type       TEXT NOT NULL,
    stored_path     TEXT NOT NULL,
    sha256          TEXT NOT NULL,
    file_size       INTEGER NOT NULL,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    available       INTEGER NOT NULL DEFAULT 1,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS upstream_comments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    approval_code   TEXT NOT NULL REFERENCES upstream_approvals(approval_code) ON DELETE CASCADE,
    content         TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS upstream_faults (
    scope           TEXT PRIMARY KEY,
    enabled         INTEGER NOT NULL DEFAULT 0,
    http_status     INTEGER NOT NULL DEFAULT 500
);

CREATE INDEX IF NOT EXISTS idx_upstream_attachments_code ON upstream_attachments(approval_code);
CREATE INDEX IF NOT EXISTS idx_upstream_comments_code    ON upstream_comments(approval_code);
