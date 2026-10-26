# 自动化安全评估系统 API 说明

对应需求文档：`项目需求.md` v1.3 第 9、10 章。  
Base URL：`http://127.0.0.1:8000`；接口前缀 `/api`。  
OpenAPI：`http://127.0.0.1:8000/docs`。

## 1. 通用约定

- 编码：UTF-8；请求与响应为 JSON（报告下载除外）。
- 认证：除下列接口外，均需 `Authorization: Bearer <JWT>`：
  - `POST /api/system/init`
  - `POST /api/system/login`
  - `GET /api/system/status`
  - `WS /api/projects/{project_id}/stream`（Token 通过查询参数传递）
- 时间：ISO 8601，带 `+08:00`。
- 成功包络：

```json
{ "code": 0, "message": "ok", "data": {} }
```

- 失败包络：`code` 为业务码，HTTP 状态码同时设置；`data` 通常为 `null`。
- 列表接口 `data` 直接为数组，不使用分页对象包裹。

## 2. 错误码

| code | 名称 | HTTP | 说明 |
| --- | --- | --- | --- |
| 0 | OK | 2xx | 成功 |
| 1001 | INVALID_CREDENTIALS | 401 | 用户名或密码错误 |
| 1002 | UNAUTHORIZED | 401 | 未登录、Token 无效或过期 |
| 1003 | FORBIDDEN | 403 | 无权限 |
| 1004 | USER_DISABLED | 403 | 账号禁用 |
| 1005 | SYSTEM_ALREADY_INITIALIZED | 409 | 系统已初始化 |
| 1006 | SYSTEM_NOT_INITIALIZED | 409 | 系统未初始化 |
| 2001 | PROJECT_NOT_FOUND | 404 | 项目不存在 |
| 2002 | PROJECT_STATE_CONFLICT | 409 | 项目状态冲突 |
| 2003 | PROJECT_CONCURRENCY_LIMIT | 409 | 并发达到上限 |
| 2004 | SOURCE_PATH_INVALID | 422 | 源码路径非法 |
| 2005 | PROJECT_RUNNING_CANNOT_DELETE | 409 | 运行中不可删除 |
| 2007 | DELETE_CONFIRM_REQUIRED | 400 | 删除未确认 |
| 2008 | SOURCE_TYPE_NOT_SUPPORTED | 422 | 源码类型不支持 |
| 3001 | ENVIRONMENT_CREATE_FAILED | 500 | 环境创建失败 |
| 3002 | ENVIRONMENT_UNAVAILABLE | 503 | 环境不可用 |
| 3003 | COMMAND_NOT_ALLOWED | 403 | 命令不在白名单 |
| 3004 | COMMAND_TIMEOUT | 408 | 命令超时 |
| 3005 | PATH_OUT_OF_SCOPE | 403 | 路径越界 |
| 3006 | ENVIRONMENT_STATE_CONFLICT | 409 | 环境状态冲突 |
| 3007 | ENVIRONMENT_NOT_FOUND | 404 | 环境不存在 |
| 3008 | SOURCE_SYNC_FAILED | 500 | 源码同步失败 |
| 4001 | STAGE_STATE_CONFLICT | 409 | 阶段状态冲突 |
| 4002 | STAGE_TIMEOUT | 408 | 阶段超时 |
| 5001 | VULNERABILITY_NOT_FOUND | 404 | 漏洞不存在 |
| 5003 | INVALID_PATH_ITEM | 422 | 路径步骤非法 |
| 6001 | ATTACK_PATH_NOT_FOUND | 404 | 攻击路径不存在 |
| 7001 | REPORT_NOT_READY | 404 | 报告未生成 |
| 7002 | REPORT_GENERATE_FAILED | 500 | 报告生成失败 |
| 8001 | CONFIG_INVALID | 422 | 配置键或值非法 |
| 9001 | LLM_REQUEST_FAILED | 502 | LLM 调用失败 |
| 9002 | WS_UNAUTHORIZED | — | WS 鉴权失败（关闭码 4401） |
| 9999 | INTERNAL_ERROR | 500 | 未预期错误 / 通用参数校验失败 |

## 3. 认证

### POST `/api/system/init`

请求：`{"username": "admin", "password": "Admin@12345"}`  
成功 `201`：`data = {id, username, role: "admin", status: "active"}`  
错误：`409/1005`、`422`。

### POST `/api/system/login`

请求：`{"username": "demo", "password": "demo12345"}`  
成功 `200`：

```json
{
  "token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 86400,
  "user": { "id": 2, "username": "demo", "role": "user" }
}
```

错误：`401/1001`、`403/1004`。

### GET `/api/system/me`

成功：`{id, username, role, status, created_at}`。

### GET `/api/system/status`

匿名。成功：

```json
{
  "initialized": true,
  "llm_configured": false,
  "isolation_available": { "docker": true, "local": false }
}
```

## 4. 项目

### POST `/api/projects`

```json
{
  "project_name": "vuln-demo 安全评估",
  "source_type": "local_path",
  "source_path": "D:\\pythoncode\\auto\\examples\\vuln-demo",
  "task_content": "重点检查 SQL 注入、命令注入、文件操作与越权。",
  "isolation_type": "docker"
}
```

成功 `201`：项目对象，含 `isolation: {env_type, env_status}`。  
错误：`422/2004`、`422/2008`。

### GET `/api/projects`

查询参数：`status`、`keyword`、`created_by`（管理员）、`limit`（默认 100，最大 500）、`offset`。  
列表项：`id`、`project_name`、`source_type`、`source_path`、`project_status`、`created_by`、`created_by_username`、`created_at`、`last_started_at`、`last_finished_at`。

### GET `/api/projects/{project_id}`

返回项目基本信息、`current_run_no`、`isolation`、`counts`（漏洞/已验证/路径数量）、`report_status`（`none|generating|ready|failed`）。

### POST `/api/projects/{project_id}/start`

成功：`{project_id, run_no, project_status: "running", started_at}`。  
错误：`409/2002`、`409/2003`。

### POST `/api/projects/{project_id}/stop`

成功：`{project_id, project_status: "stopped", stopped_at}`。

### DELETE `/api/projects/{project_id}?confirm=true`

成功：`{deleted: true, warnings: []}`。  
错误：`400/2007`、`409/2005`。

### GET `/api/projects/{project_id}/stages`

查询：`run_no`（默认最新轮次）。返回阶段数组：`id`、`run_no`、`stage_name`、`stage_status`、`started_at`、`finished_at`、`error_message`。

### GET `/api/projects/{project_id}/workers`

查询：`run_no`、`stage_id`、`stage_name`。返回角色任务数组。

## 5. 结果

### GET `/api/projects/{project_id}/vulnerabilities`

查询：`run_no`（默认最新）、`risk_level`、`verify_status`、`keyword`。  
列表项：`id`、`vuln_code`、`vuln_title`、`risk_level`、`file_path`、`verify_status`、`created_at`。

### GET `/api/projects/{project_id}/vulnerabilities/{vuln_id}`

列表项字段 + `impact_text`、`condition_text`、`evidence_text`、`reproduce_steps_text`、`verify_code_text`。

### GET `/api/projects/{project_id}/attack-paths`

查询：`run_no`。列表项：`id`、`path_code`、`path_title`、`path_summary`、`vuln_count`、`max_risk_level`、`final_impact_text`、`created_at`。

### GET `/api/projects/{project_id}/attack-paths/{path_id}`

路径信息 + `items[]`（`step_order`、`step_text`、漏洞 `vuln_code`、`vuln_title`、`risk_level`、`file_path`、`verify_status`）。

### GET `/api/projects/{project_id}/report`

查询：`run_no`。返回 `{report_id, run_no, report_markdown, report_html, report_file_path, created_at}`。未就绪返回 `404/7001`。

### GET `/api/projects/{project_id}/report/download`

返回 HTML 文件流：

```text
Content-Type: text/html; charset=utf-8
Content-Disposition: attachment; filename="report_{project_id}_{run_no}.html"
```

## 6. 监控

### GET `/api/projects/{project_id}/logs`

查询：`level`、`stage_id`、`worker_task_id`、`limit`（默认 200，最大 1000）、`before_id`。按 `id` 升序。

### GET `/api/projects/{project_id}/resources`

查询：`limit`（默认 300，最大 2000）、`since`。按 `recorded_at` 升序，字段：`cpu_usage`、`memory_usage`、`token_count`、`recorded_at`。

### GET `/api/projects/{project_id}/messages`

查询：`limit`（默认 100，最大 500）、`before_id`。返回聊天消息数组。

## 7. 配置与管理（管理员）

### GET `/api/system/config`

返回扁平键值对象，`llm.api_key` 脱敏（如 `sk-****abcd`），按 `config_key` 排序。

### PUT `/api/system/config`

部分更新，值为原生 JSON 类型。示例：

```json
{
  "runtime.max_concurrent_projects": 2,
  "runtime.stage_timeout_minutes": 15,
  "llm.api_key": "sk-xxxx"
}
```

- `llm.api_key` 省略或 `null` 表示不修改，空字符串表示清空。
- 未知键、类型或范围非法返回 `422/8001`。
- 返回更新后的完整配置（脱敏）。

### GET `/api/system/users`

仅管理员。返回 `[{id, username, role}]`，用于项目列表按创建人筛选。

### GET `/api/system/logs`

查询：`project_id`、`level`、`limit`、`before_id`。系统日志的 `project_id` 为 `null`。

### GET `/api/system/isolation-envs`

查询：`env_status`、`env_type`、`project_id`。字段：`id`、`project_id`、`project_name`、`env_type`、`env_ref`、`env_status`、`last_error`、`updated_at`。

### POST `/api/system/isolation-envs/{env_id}/cleanup`

停止并销毁非 `running` 容器，删除 VM 工作区，状态置 `destroyed`。  
错误：`409/3006`（运行中）、`404/3007`。

## 8. WebSocket

地址：`ws://127.0.0.1:8000/api/projects/{project_id}/stream?token=<JWT>`

关闭码：

| 码 | 含义 |
| --- | --- |
| 4401 | 未认证 / Token 无效或过期 |
| 4403 | 无权限 |
| 4404 | 项目不存在 |
| 4410 | 服务端内部错误 / 心跳超时 |

包络：

```json
{
  "type": "stage_status",
  "project_id": 1,
  "timestamp": "2026-10-21T19:55:00+08:00",
  "data": {}
}
```

8 类业务消息：

1. `project_status`：`{project_id, project_status, run_no, updated_at}`
2. `stage_status`：`{project_id, stage_id, stage_name, stage_status, run_no}`
3. `worker_status`：`{worker_task_id, worker_role, task_status, stage_id, project_id}`
4. `chat_message`：`{message_id, worker_role, message_type, message_text, created_at}`
5. `runtime_log`：`{log_id, log_level, log_content, stage_id, worker_task_id, created_at}`
6. `resource_usage`：`{cpu_usage, memory_usage, token_count, recorded_at}`
7. `vulnerability_found`：`{vuln_id, vuln_code, vuln_title, risk_level, file_path}`
8. `report_ready`：`{project_id, report_id, run_no, report_file_path}`

心跳：

```json
{"type": "ping"}
{"type": "pong", "timestamp": "2026-10-21T19:55:30+08:00"}
```

连接建立并鉴权后依次发送快照：1 条 `project_status`、当前轮次各阶段 `stage_status`、最近角色任务 `worker_status`、最近 50 条 `runtime_log`、最近 20 条 `chat_message`。快照完成后进入实时推送。
