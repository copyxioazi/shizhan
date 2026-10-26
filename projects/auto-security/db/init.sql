-- ============================================================
-- 自动化安全评估系统 数据库初始化脚本
-- 目标数据库：PostgreSQL 16（UTF-8）
--
-- 用法（在 VM 上，数据库已创建）：
--   psql -U postgres -d sec_eval -f db/init.sql
-- 或从 Windows：
--   psql "postgresql://postgres:<password>@<vm-ip>:5432/sec_eval" -f db/init.sql
--
-- 若数据库尚未创建（docker-compose 已通过 POSTGRES_DB 创建 sec_eval）：
--   CREATE DATABASE sec_eval WITH ENCODING 'UTF8' TEMPLATE template0;
--   \c sec_eval
--   然后执行本脚本。
--
-- 脚本可重复执行：表、索引、默认配置与演示用户均为幂等创建。
-- 枚举统一使用 VARCHAR + CHECK；时间统一 TIMESTAMPTZ（UTC 存储）。
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. users
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    username      VARCHAR(64)  NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role          VARCHAR(16)  NOT NULL DEFAULT 'user'
                  CHECK (role IN ('admin', 'user')),
    status        VARCHAR(16)  NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active', 'disabled')),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_users_username_lower ON users (lower(username));

-- ------------------------------------------------------------
-- 2. projects
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS projects (
    id             BIGSERIAL PRIMARY KEY,
    project_name   VARCHAR(128)  NOT NULL,
    source_type    VARCHAR(16)   NOT NULL DEFAULT 'local_path'
                   CHECK (source_type IN ('local_path', 'git_repo')),
    source_path    VARCHAR(1024) NOT NULL,
    task_content   TEXT          NOT NULL,
    project_status VARCHAR(16)   NOT NULL DEFAULT 'created'
                   CHECK (project_status IN ('created', 'running', 'completed', 'failed', 'stopped')),
    created_by     BIGINT        NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_projects_created_by ON projects (created_by);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects (project_status);
CREATE INDEX IF NOT EXISTS idx_projects_created_at ON projects (created_at);

-- ------------------------------------------------------------
-- 3. runtime_stages
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS runtime_stages (
    id            BIGSERIAL PRIMARY KEY,
    project_id    BIGINT       NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    run_no        INTEGER      NOT NULL,
    stage_name    VARCHAR(32)  NOT NULL
                  CHECK (stage_name IN ('environment_scan', 'code_analysis', 'vulnerability_verify', 'report_generate')),
    stage_status  VARCHAR(16)  NOT NULL DEFAULT 'pending'
                  CHECK (stage_status IN ('pending', 'running', 'success', 'failed', 'cancelled')),
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ,
    error_message TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_stage_run ON runtime_stages (project_id, run_no, stage_name);
CREATE INDEX IF NOT EXISTS idx_stages_project ON runtime_stages (project_id, run_no);

-- ------------------------------------------------------------
-- 4. worker_tasks
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS worker_tasks (
    id             BIGSERIAL PRIMARY KEY,
    project_id     BIGINT      NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    stage_id       BIGINT      NOT NULL REFERENCES runtime_stages (id) ON DELETE CASCADE,
    worker_role    VARCHAR(32) NOT NULL
                   CHECK (worker_role IN ('general', 'env_checker', 'code_analyst', 'vuln_verifier', 'report_writer', 'ops_assistant')),
    task_content   TEXT        NOT NULL,
    task_status    VARCHAR(16) NOT NULL DEFAULT 'idle'
                   CHECK (task_status IN ('idle', 'running', 'success', 'failed', 'cancelled')),
    result_summary TEXT,
    error_message  TEXT,
    started_at     TIMESTAMPTZ,
    finished_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_workers_project ON worker_tasks (project_id);
CREATE INDEX IF NOT EXISTS idx_workers_stage ON worker_tasks (stage_id);
CREATE INDEX IF NOT EXISTS idx_workers_role ON worker_tasks (worker_role);

-- ------------------------------------------------------------
-- 5. vulnerabilities
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS vulnerabilities (
    id                  BIGSERIAL PRIMARY KEY,
    project_id          BIGINT       NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    run_no              INTEGER      NOT NULL,
    vuln_code           VARCHAR(32)  NOT NULL,
    vuln_title          VARCHAR(255) NOT NULL,
    risk_level          VARCHAR(16)  NOT NULL
                        CHECK (risk_level IN ('critical', 'high', 'medium', 'low', 'info')),
    file_path           VARCHAR(1024) NOT NULL,
    condition_text      TEXT         NOT NULL,
    evidence_text       TEXT         NOT NULL,
    verify_status       VARCHAR(16)  NOT NULL DEFAULT 'pending'
                        CHECK (verify_status IN ('pending', 'verified', 'failed', 'skipped')),
    reproduce_steps_text TEXT,
    verify_code_text    TEXT,
    impact_text         TEXT         NOT NULL,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_vuln_code ON vulnerabilities (project_id, run_no, vuln_code);
-- 同一项目同一轮次内 file_path + vuln_title 去重
CREATE UNIQUE INDEX IF NOT EXISTS uk_vuln_dedup
    ON vulnerabilities (project_id, run_no, md5(file_path || '|' || vuln_title));
CREATE INDEX IF NOT EXISTS idx_vuln_project ON vulnerabilities (project_id, run_no);
CREATE INDEX IF NOT EXISTS idx_vuln_risk ON vulnerabilities (risk_level);

-- ------------------------------------------------------------
-- 6. attack_paths
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS attack_paths (
    id                BIGSERIAL PRIMARY KEY,
    project_id        BIGINT       NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    run_no            INTEGER      NOT NULL,
    path_code         VARCHAR(32)  NOT NULL,
    path_title        VARCHAR(255) NOT NULL,
    path_summary      TEXT         NOT NULL,
    final_impact_text TEXT         NOT NULL,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_path_code ON attack_paths (project_id, run_no, path_code);
CREATE INDEX IF NOT EXISTS idx_paths_project ON attack_paths (project_id, run_no);

-- ------------------------------------------------------------
-- 7. attack_path_items
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS attack_path_items (
    id         BIGSERIAL PRIMARY KEY,
    path_id    BIGINT  NOT NULL REFERENCES attack_paths (id) ON DELETE CASCADE,
    vuln_id    BIGINT  NOT NULL REFERENCES vulnerabilities (id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    step_text  TEXT    NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_path_step ON attack_path_items (path_id, step_order);
CREATE INDEX IF NOT EXISTS idx_items_vuln ON attack_path_items (vuln_id);

-- ------------------------------------------------------------
-- 8. chat_messages
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_messages (
    id           BIGSERIAL PRIMARY KEY,
    project_id   BIGINT      NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    worker_role  VARCHAR(32) NOT NULL
                 CHECK (worker_role IN ('general', 'env_checker', 'code_analyst', 'vuln_verifier', 'report_writer', 'ops_assistant', 'system')),
    message_type VARCHAR(16) NOT NULL
                 CHECK (message_type IN ('thought', 'analysis', 'evidence', 'conclusion', 'system')),
    message_text TEXT        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_project ON chat_messages (project_id, id);

-- ------------------------------------------------------------
-- 9. runtime_logs
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS runtime_logs (
    id             BIGSERIAL PRIMARY KEY,
    project_id     BIGINT REFERENCES projects (id) ON DELETE CASCADE,
    stage_id       BIGINT REFERENCES runtime_stages (id) ON DELETE CASCADE,
    worker_task_id BIGINT REFERENCES worker_tasks (id) ON DELETE CASCADE,
    log_level      VARCHAR(16) NOT NULL
                   CHECK (log_level IN ('debug', 'info', 'warn', 'error')),
    log_content    TEXT        NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_logs_project ON runtime_logs (project_id, id);
CREATE INDEX IF NOT EXISTS idx_logs_level ON runtime_logs (log_level);
CREATE INDEX IF NOT EXISTS idx_logs_created ON runtime_logs (created_at);

-- ------------------------------------------------------------
-- 10. resource_usages
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS resource_usages (
    id           BIGSERIAL PRIMARY KEY,
    project_id   BIGINT        NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    cpu_usage    DECIMAL(6, 2) NOT NULL,
    memory_usage DECIMAL(10, 2) NOT NULL,
    token_count  INTEGER       NOT NULL DEFAULT 0,
    recorded_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_res_project ON resource_usages (project_id, recorded_at);

-- ------------------------------------------------------------
-- 11. reports
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reports (
    id               BIGSERIAL PRIMARY KEY,
    project_id       BIGINT        NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    run_no           INTEGER       NOT NULL,
    report_markdown  TEXT          NOT NULL,
    report_html      TEXT          NOT NULL,
    report_file_path VARCHAR(1024) NOT NULL,
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_report_run ON reports (project_id, run_no);

-- ------------------------------------------------------------
-- 12. system_configs
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS system_configs (
    id           BIGSERIAL PRIMARY KEY,
    config_key   VARCHAR(64)  NOT NULL UNIQUE,
    config_value JSONB        NOT NULL,
    description  VARCHAR(255),
    updated_by   BIGINT REFERENCES users (id) ON DELETE SET NULL,
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_config_key ON system_configs (config_key);

-- ------------------------------------------------------------
-- 13. isolation_envs
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS isolation_envs (
    id         BIGSERIAL PRIMARY KEY,
    project_id BIGINT       NOT NULL UNIQUE REFERENCES projects (id) ON DELETE CASCADE,
    env_type   VARCHAR(16)  NOT NULL DEFAULT 'docker'
               CHECK (env_type IN ('docker', 'local')),
    env_ref    VARCHAR(255),
    env_status VARCHAR(16)  NOT NULL DEFAULT 'pending'
               CHECK (env_status IN ('pending', 'creating', 'ready', 'running', 'stopped', 'destroyed', 'failed')),
    last_error TEXT,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_env_status ON isolation_envs (env_status);
CREATE INDEX IF NOT EXISTS idx_env_type ON isolation_envs (env_type);

-- ============================================================
-- 默认配置（第 17.1 节）
-- ============================================================
INSERT INTO system_configs (config_key, config_value, description) VALUES
    ('isolation.default_type',           '"docker"'::jsonb,           '新建项目默认隔离类型'),
    ('sandbox.image',                    '"ase-sandbox:1.0"'::jsonb,   '沙箱镜像'),
    ('sandbox.cpu_limit',                '1.0'::jsonb,                 '单容器 CPU 核数上限'),
    ('sandbox.memory_limit_mb',          '512'::jsonb,                 '单容器内存上限（MB）'),
    ('sandbox.pids_limit',               '128'::jsonb,                 '单容器最大进程数'),
    ('sandbox.network_enabled',          'false'::jsonb,               '是否允许沙箱访问外网'),
    ('sandbox.command_timeout_seconds',  '60'::jsonb,                  '单条命令超时（秒）'),
    ('sandbox.output_limit_bytes',       '8192'::jsonb,                '命令输出截断上限（字节）'),
    ('sandbox.command_allowlist',        '["python","python3"]'::jsonb, '命令白名单'),
    ('runtime.max_concurrent_projects',  '2'::jsonb,                   '同时运行项目数'),
    ('runtime.stage_timeout_minutes',    '15'::jsonb,                  '单阶段超时（分钟）'),
    ('runtime.resource_sample_seconds',  '5'::jsonb,                   '资源采样间隔（秒）'),
    ('runtime.retention_days',           '30'::jsonb,                  '过程数据保留天数'),
    ('exec.max_files',                   '5000'::jsonb,                '目录遍历最大文件数'),
    ('orchestration.engine',             '"fixed"'::jsonb,             '阶段编排引擎：fixed 或 langgraph'),
    ('orchestration.analysis_mode',      '"one_shot"'::jsonb,          '代码分析模式：one_shot 或 react'),
    ('orchestration.react_max_steps',    '5'::jsonb,                   'ReAct 工具循环最大轮次'),
    ('orchestration.react_max_tokens',   '8000'::jsonb,                'ReAct 工具循环 token 预算'),
    ('orchestration.react_tool_output_chars', '6000'::jsonb,           'ReAct 单次工具输出截断字符数'),
    ('orchestration.verify_max_retries', '0'::jsonb,                  '验证失败后的最大重规划轮次'),
    ('llm.base_url',                     '""'::jsonb,                  'OpenAI 兼容接口地址'),
    ('llm.api_key',                      '""'::jsonb,                  'API Key（只写，读取脱敏）'),
    ('llm.model',                        '""'::jsonb,                  '模型名称'),
    ('llm.timeout_seconds',              '60'::jsonb,                  '单次调用超时（秒）'),
    ('llm.max_retries',                  '2'::jsonb,                   '调用失败重试次数'),
    ('llm.temperature',                  '0.2'::jsonb,                 '采样温度'),
    ('llm.max_tokens',                   '4096'::jsonb,                '单次最大输出 token')
ON CONFLICT (config_key) DO NOTHING;

-- ============================================================
-- 演示普通用户：demo / demo12345
-- ============================================================
INSERT INTO users (username, password_hash, role, status)
VALUES (
    'demo',
    '$2b$12$XH8wo9yW5DmQmB2AHNYY7eIGLE6pIZH1hVQeqhJBK15t1VXmuWdvC',
    'user',
    'active'
)
ON CONFLICT DO NOTHING;

COMMIT;
