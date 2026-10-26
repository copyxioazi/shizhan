# 工具调用说明

7 个工具保持同步签名，REST 层通过 `{"success": true, "data": ...}` 返回。
当前进度：7 个工具与异步一键审查全部实现，包含 PDF/DOCX/OCR 解析、
6 种规则匹配、结果保存与幂等回写。

## 7 个同步工具

| 工具 | 签名 | REST | 状态 |
|---|---|---|---|
| 待办拉取 | `list_pending_contract_approvals(limit)` | `POST /api/tools/list_pending_contract_approvals?limit=50` | 已实现 |
| 审批详情 | `get_contract_approval(instance_id)` | `GET /api/tools/get_contract_approval/{instance_id}` | 已实现 |
| 附件下载 | `download_contract_attachment(instance_id, attachment_id, file_name)` | `POST /api/tools/download_contract_attachment` | 已实现 |
| 文档解析 | `parse_contract_document(document_id)` | `POST /api/tools/parse_contract_document` | 已实现 |
| 规则审查 | `run_contract_rules(case_id)` | `POST /api/tools/run_contract_rules` | 已实现 |
| 结果保存 | `save_review_result(case_id, overall_risk_level, summary_text, focus_points_json, comment_text)` | `POST /api/tools/save_review_result` | 已实现 |
| 评论回写 | `write_approval_comment(instance_id, review_id)` | `POST /api/tools/write_approval_comment` | 已实现 |

## ID 语义

- `instance_id` = `approval_code`（审批编号，唯一业务标识）。
- `case_id` = `approval_tasks.id`。
- `document_id` = `approval_attachments.id`。
- 下载工具的 `attachment_id` 是 Mock 上游附件 ID。
- 去重键：`approval_code`。

## 响应约定

成功：

```json
{"success": true, "data": {}}
```

工具/任务级失败：

```json
{
  "success": false,
  "error": {
    "code": "MISSING_ATTACHMENT",
    "message": "附件不存在或不可下载",
    "details": {}
  }
}
```

未知 ID：HTTP 404；表单非法：422；上游不可用：502；未实现：501；
附件缺失/下载失败/回写失败：409（`MISSING_ATTACHMENT`、`DOWNLOAD_FAILED`、
`CHECKSUM_MISMATCH`、`COMMENT_WRITE_FAILED`）。

## 示例请求

### 1. 拉取待办（按 approval_code 去重）

```bash
curl -X POST "http://127.0.0.1:8000/api/tools/list_pending_contract_approvals?limit=50"
```

```json
{
  "success": true,
  "data": [
    {
      "instance_id": "APV-2026-001",
      "approval_code": "APV-2026-001",
      "case_id": 4,
      "approval_title": "设备采购合同审批",
      "task_status": "pending",
      "write_status": "not_written",
      "stage": "idle",
      "created": true
    }
  ]
}
```

重复拉取时 `created=false`，不会新增任务。

### 2. 审批详情

```bash
curl http://127.0.0.1:8000/api/tools/get_contract_approval/APV-2026-001
```

返回上游审批信息、`form_data`、附件（含本地 `document_id` / `download_status` /
`is_primary`）、本地任务状态、解析与审查结果摘要。

### 3. 下载附件

```bash
curl -X POST http://127.0.0.1:8000/api/tools/download_contract_attachment \
  -H 'Content-Type: application/json' \
  -d '{"instance_id":"APV-2026-001","attachment_id":1,"file_name":"设备采购合同.pdf"}'
```

```json
{
  "success": true,
  "data": {
    "document_id": 1,
    "file_path": "data/attachments/APV-2026-001/1_设备采购合同.pdf",
    "sha256": "9f51...",
    "file_size": 78758,
    "checksum_verified": true,
    "download_status": "success"
  }
}
```

### 4. 解析文档

```bash
curl -X POST http://127.0.0.1:8000/api/tools/parse_contract_document \
  -H 'Content-Type: application/json' \
  -d '{"document_id": 1}'
```

返回 `parse_status`（`success/partial/failed`）、`basic_info`、`clause_info`、
页数、是否使用 OCR、缺失字段/条款和警告。每项字段包含
`{value, raw_text, position, status}`。

### 5. 执行规则审查

```bash
curl -X POST http://127.0.0.1:8000/api/tools/run_contract_rules \
  -H 'Content-Type: application/json' \
  -d '{"case_id": 4}'
```

返回 `overall_risk_level`、`hits`（规则名、等级、证据、位置、建议）和
`focus_points`。非法 JSON/正则的规则会被跳过，并在 `skipped_rules` 与任务日志中记录。

### 6. 保存审查结果

```bash
curl -X POST http://127.0.0.1:8000/api/tools/save_review_result \
  -H 'Content-Type: application/json' \
  -d '{
    "case_id": 4,
    "overall_risk_level": "high",
    "summary_text": "本次审查共命中 4 条风险……",
    "focus_points_json": ["预付款比例超过30%"],
    "comment_text": "【合同审查结论】整体风险：高风险"
  }'
```

同一任务重复保存会 upsert 唯一的 `review_results` 行。

### 7. 幂等回写

```bash
curl -X POST http://127.0.0.1:8000/api/tools/write_approval_comment \
  -H 'Content-Type: application/json' \
  -d '{"instance_id":"APV-2026-001","review_id":1}'
```

幂等键为 `contract-review:{approval_code}:{review_id}`。本地已 `success` 时直接
短路；上游重复键返回已有评论（`duplicate=true`）。回写失败时任务进入
`blocked + write_status=failed`，故障恢复后重试只重写评论。

## 同步与异步

- 7 个工具保持同步，供脚本逐步调用。
- 一键审查是异步入口：
  - `POST /api/tasks/{task_id}/full-review` → 202
  - `POST /api/tasks/{task_id}/retry` → 202，只有 blocked 任务可重试
  - `GET /api/tasks/{task_id}/status` → 轮询，`terminal=true` 表示 done/blocked

流水线阶段：`download → parse → review → save → write`。重试会从失败阶段继续：

| 失败阶段 | 重试行为 |
|---|---|
| `download` | 重新下载全部附件 |
| `parse` | 解析现有主附件 |
| `review` | 重跑规则 |
| `save` | 用现有命中重新生成并保存结果 |
| `write` | 只重写评论，不重新解析 |

## 合同内容只读接口

```text
GET /api/tasks/{task_id}/content
```

按本地 `case_id` 返回解析后的合同内容，用于“查看原文”：

- `parse_status`、`parse_error`、`warnings`
- `basic_info`、`clause_info`
- `text_content`：解析全文
- `segments`：PDF 页 / DOCX 段落 / OCR 行的位置映射
- `hits`：规则命中、证据片段、结构化位置

未解析时 `parse_status=null`、`text_content=""`。

## 管理端规则接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/admin/rules` | 规则列表 |
| POST | `/api/admin/rules` | 新增规则（保存时校验 JSON/正则） |
| PUT | `/api/admin/rules/{id}` | 修改规则 |
| DELETE | `/api/admin/rules/{id}` | 删除规则；被历史命中引用时返回 `RULE_IN_USE`，请改为停用 |
