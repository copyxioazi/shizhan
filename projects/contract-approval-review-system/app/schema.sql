-- 本地审查库：data/app.db
-- 8 张需求必需表；+ 号字段为最小必要扩展。

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS approval_tasks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    approval_code       TEXT    NOT NULL UNIQUE,
    approval_title      TEXT    NOT NULL,
    applicant_name      TEXT    NOT NULL,
    task_status         TEXT    NOT NULL DEFAULT 'pending'
                        CHECK (task_status IN ('pending','parsing','reviewing','blocked','done')),
    write_status        TEXT    NOT NULL DEFAULT 'not_written'
                        CHECK (write_status IN ('not_written','writing','success','failed')),
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL,
    -- +
    applied_at          TEXT,
    form_data_json      TEXT,
    upstream_status     TEXT,
    stage               TEXT    NOT NULL DEFAULT 'idle'
                        CHECK (stage IN ('idle','queued','download','parse','review','save','write','done')),
    resume_stage        TEXT
                        CHECK (resume_stage IS NULL OR resume_stage IN ('download','parse','review','save','write')),
    retry_count         INTEGER NOT NULL DEFAULT 0,
    last_error_code     TEXT,
    last_error          TEXT,
    queued_at           TEXT,
    started_at          TEXT,
    finished_at         TEXT
);

CREATE TABLE IF NOT EXISTS approval_attachments (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id                 INTEGER NOT NULL REFERENCES approval_tasks(id) ON DELETE CASCADE,
    file_name               TEXT    NOT NULL,
    file_type               TEXT    NOT NULL,
    file_path               TEXT,
    download_status         TEXT    NOT NULL DEFAULT 'pending'
                            CHECK (download_status IN ('pending','downloading','success','failed','missing')),
    created_at              TEXT    NOT NULL,
    -- +
    upstream_attachment_id  TEXT    NOT NULL,
    sha256                  TEXT,
    file_size               INTEGER,
    sort_order              INTEGER NOT NULL DEFAULT 0,
    is_primary              INTEGER NOT NULL DEFAULT 0,
    download_error          TEXT,
    updated_at              TEXT,
    UNIQUE (task_id, upstream_attachment_id)
);

CREATE TABLE IF NOT EXISTS contract_parses (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id                 INTEGER NOT NULL UNIQUE REFERENCES approval_tasks(id) ON DELETE CASCADE,
    basic_info_json         TEXT,
    clause_info_json        TEXT,
    parse_status            TEXT    NOT NULL DEFAULT 'pending'
                            CHECK (parse_status IN ('pending','success','partial','failed')),
    parse_error             TEXT,
    created_at              TEXT    NOT NULL,
    -- +
    source_attachment_id    INTEGER REFERENCES approval_attachments(id),
    sha256                  TEXT,
    page_count              INTEGER,
    ocr_used                INTEGER NOT NULL DEFAULT 0,
    text_length             INTEGER,
    warnings_json           TEXT,
    -- + 规则执行时复用的原文与位置映射（避免重复解析/OCR）
    text_content            TEXT,
    segments_json           TEXT,
    parser_version          TEXT,
    duration_ms             INTEGER,
    updated_at              TEXT
);

CREATE TABLE IF NOT EXISTS review_rules (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_code       TEXT    NOT NULL UNIQUE,
    rule_name       TEXT    NOT NULL,
    risk_level      TEXT    NOT NULL CHECK (risk_level IN ('low','medium','high')),
    rule_status     TEXT    NOT NULL DEFAULT 'enabled'
                    CHECK (rule_status IN ('enabled','disabled')),
    match_mode      TEXT    NOT NULL
                    CHECK (match_mode IN ('keyword','all_keywords','regex','absence','field_check','numeric_threshold')),
    match_text      TEXT    NOT NULL,
    suggestion_text TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    -- +
    category        TEXT,
    created_at      TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS rule_hits (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id             INTEGER NOT NULL REFERENCES approval_tasks(id) ON DELETE CASCADE,
    rule_id             INTEGER NOT NULL REFERENCES review_rules(id),
    evidence_text       TEXT    NOT NULL,
    evidence_position   TEXT    NOT NULL,
    hit_status          TEXT    NOT NULL DEFAULT 'hit'
                        CHECK (hit_status IN ('hit','no_hit','skipped')),
    created_at          TEXT    NOT NULL,
    -- +
    rule_name_snapshot  TEXT,
    risk_level_snapshot TEXT,
    suggestion_snapshot TEXT,
    matched_value       TEXT,
    UNIQUE (task_id, rule_id)
);

CREATE TABLE IF NOT EXISTS review_results (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id             INTEGER NOT NULL UNIQUE REFERENCES approval_tasks(id) ON DELETE CASCADE,
    overall_risk_level  TEXT    NOT NULL CHECK (overall_risk_level IN ('low','medium','high')),
    summary_text        TEXT    NOT NULL,
    focus_points_json   TEXT    NOT NULL,
    comment_text        TEXT    NOT NULL,
    created_at          TEXT    NOT NULL,
    -- +
    updated_at          TEXT,
    llm_enhanced        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS comment_logs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id             INTEGER NOT NULL REFERENCES approval_tasks(id) ON DELETE CASCADE,
    write_status        TEXT    NOT NULL CHECK (write_status IN ('writing','success','failed')),
    write_response_text TEXT,
    created_at          TEXT    NOT NULL,
    -- +
    review_id           INTEGER REFERENCES review_results(id),
    attempt_no          INTEGER NOT NULL DEFAULT 1,
    idempotency_key     TEXT,
    http_status         INTEGER,
    error_code          TEXT
);

CREATE TABLE IF NOT EXISTS task_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER REFERENCES approval_tasks(id) ON DELETE CASCADE,
    log_level   TEXT    NOT NULL CHECK (log_level IN ('DEBUG','INFO','WARN','ERROR')),
    log_type    TEXT    NOT NULL,
    log_content TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    -- +
    stage       TEXT,
    detail_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_status         ON approval_tasks(task_status);
CREATE INDEX IF NOT EXISTS idx_tasks_updated        ON approval_tasks(updated_at);
CREATE INDEX IF NOT EXISTS idx_attachments_task     ON approval_attachments(task_id);
CREATE INDEX IF NOT EXISTS idx_parses_task          ON contract_parses(task_id);
CREATE INDEX IF NOT EXISTS idx_hits_task            ON rule_hits(task_id);
CREATE INDEX IF NOT EXISTS idx_results_task         ON review_results(task_id);
CREATE INDEX IF NOT EXISTS idx_comment_logs_task    ON comment_logs(task_id);
CREATE INDEX IF NOT EXISTS idx_task_logs_task_time  ON task_logs(task_id, created_at);

-- Mock 上游表不在此文件：见 references/mock_schema.sql。
-- scripts/init_db.py 必须把本文件执行到 data/app.db，
-- 把 mock_schema.sql 执行到 data/mock_upstream.db。
