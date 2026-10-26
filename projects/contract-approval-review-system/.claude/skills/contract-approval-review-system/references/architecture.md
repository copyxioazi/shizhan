# 合同审批审查系统完整设计

> 优先级：`decisions.md` > 本文 > 需求文档。本文中的实现细节如与锁定决策冲突，以 `decisions.md` 为准。

## 1. 目录与模块

```text
<project-root>\
├─ README.md
├─ requirements.txt
├─ .env.example
├─ pyproject.toml                    # pytest 配置与 marker
├─ app\
│  ├─ main.py                        # create_app、lifespan、路由注册、恢复、worker
│  ├─ config.py                      # 环境变量、路径、开关
│  ├─ db.py                          # sqlite3 连接、事务、WAL、busy_timeout
│  ├─ schema.sql
│  ├─ status.py                      # 状态/阶段/错误码常量
│  ├─ errors.py                      # ToolError、BlockedError、UpstreamError
│  ├─ api\
│  │  ├─ tools.py                    # 7 个同步 REST 包装
│  │  ├─ tasks.py                    # 一键审查、重试、状态、任务列表
│  │  └─ admin.py                    # 管理端 JSON 接口
│  ├─ web\
│  │  ├─ routes.py                   # 服务端渲染页面与表单动作
│  │  └─ viewmodels.py               # 状态文案、位置格式化、JSON 辅助
│  ├─ services\
│  │  ├─ tool_functions.py           # 7 个同步工具函数
│  │  ├─ upstream_client.py          # 唯一允许调用 /mock-upstream/* 的组件
│  │  ├─ approvals.py                # 拉取、去重、详情、本地关联
│  │  ├─ attachments.py              # 下载、校验、安全存储、主附件选择
│  │  ├─ parser\
│  │  │  ├─ service.py               # parse_contract_document 编排
│  │  │  ├─ text_document.py         # 文本段 + 全局偏移到源位置映射
│  │  │  ├─ pdf_parser.py
│  │  │  ├─ docx_parser.py
│  │  │  ├─ ocr.py                   # RapidOCR 单例、锁、PDF 栅格化
│  │  │  ├─ fields.py                # 基本信息与条款抽取
│  │  │  └─ sections.py              # 条款标题分段
│  │  ├─ rules\
│  │  │  ├─ engine.py                # 匹配分发、命中、汇总、关注点
│  │  │  ├─ matchers.py              # 6 种 match_mode
│  │  │  └─ validator.py             # 规则校验
│  │  ├─ review.py                   # 摘要/评论模板与结果持久化
│  │  ├─ llm.py                      # 可选 OpenAI 兼容润色
│  │  ├─ comments.py                 # 幂等回写与评论日志
│  │  ├─ pipeline.py                 # 可恢复同步流水线主体
│  │  ├─ queue.py                    # asyncio 队列、2 个 worker、去重
│  │  └─ logs.py                     # 任务/应用日志
│  ├─ mock_upstream\
│  │  ├─ router.py                   # /mock-upstream 路由
│  │  ├─ service.py                  # Mock DB 操作、评论、故障注入
│  │  ├─ seed.py                     # 4 个审批单与附件
│  │  └─ schema.sql                  # Mock DB
│  ├─ seed\rules.json                # 从 references/rules.seed.json 复制
│  ├─ templates\
│  └─ static\{app.js,style.css}
├─ scripts\
│  ├─ init_db.py                     # 建两个库、生成样例、种子规则/Mock
│  ├─ generate_samples.py            # 确定性 PDF/DOCX/PNG 生成
│  ├─ reset_demo.py                  # 可选清空重灌
│  └─ demo_closed_loop.py            # 完整闭环演示
├─ sample_contracts\
│  ├─ manifest.json                  # 预期结果 + SHA-256
│  ├─ apv_2026_001_purchase.pdf
│  ├─ apv_2026_002_service.docx
│  ├─ apv_2026_003_scan.png
│  └─ apv_2026_004_hidden.docx
├─ data\                             # 运行时 SQLite 与下载文件
├─ docs\{TOOLS.md,ARCHITECTURE.md,DEMO.md}
└─ tests\
   ├─ conftest.py
   ├─ test_rule_modes.py
   ├─ test_parsers.py
   ├─ test_tool_api.py
   ├─ test_pipeline_e2e.py
   ├─ test_recovery.py
   ├─ test_llm_fallback.py
   └─ test_admin.py
```

数据访问用标准库 `sqlite3`，不用 SQLAlchemy。每个操作使用短连接，WAL，`busy_timeout=5000`；OCR/HTTP 不放在数据库事务内。

## 2. 数据库

本地库 `data/app.db` 的完整 DDL 见 `references/schema.sql`。8 张必需表：

- `approval_tasks`：任务主表；`approval_code UNIQUE`；`id = case_id`。
- `approval_attachments`：附件；`upstream_attachment_id`、`sha256`、`is_primary`；`id = document_id`。
- `contract_parses`：每任务一行；`basic_info_json`、`clause_info_json`、`parse_status`、`parse_error`。
- `review_rules`：规则；`match_mode` 6 种；`match_text` 存字符串或 JSON。
- `rule_hits`：每任务每规则最多一条；保存规则名/等级/建议快照。
- `review_results`：每任务一行；总风险、摘要、关注点 JSON、评论正文。
- `comment_logs`：每次回写尝试一行；幂等键、HTTP 状态、错误码。
- `task_logs`：全链路日志；`task_id` 可为空表示拉取级错误。

Mock 库 `data/mock_upstream.db`，与本地库物理隔离；DDL 见 `references/mock_schema.sql`。

- `upstream_approvals(approval_code PK, approval_title, applicant_name, applied_at, form_data_json, status, updated_at)`
- `upstream_attachments(id PK, approval_code, file_name, file_type, stored_path, sha256, file_size, sort_order, available, updated_at)`
- `upstream_comments(id PK, approval_code, content, idempotency_key UNIQUE, created_at)`
- `upstream_faults(scope PK, enabled, http_status)`：`scope` 取 `detail|download|comment`。

## 3. 工具函数与 REST 路由

7 个函数在 `app/services/tool_functions.py` 中保持同步 `def`：

```python
def list_pending_contract_approvals(limit: int) -> list[dict]
def get_contract_approval(instance_id: str) -> dict
def download_contract_attachment(instance_id: str, attachment_id: int, file_name: str) -> dict
def parse_contract_document(document_id: int) -> dict
def run_contract_rules(case_id: int) -> dict
def save_review_result(case_id: int, overall_risk_level: str, summary_text: str,
                       focus_points_json: str | list, comment_text: str) -> dict
def write_approval_comment(instance_id: str, review_id: int) -> dict
```

| 函数 | 路由 | 说明 |
|---|---|---|
| `list_pending_contract_approvals` | `POST /api/tools/list_pending_contract_approvals?limit=50` | 拉取 Mock 待办，按 `approval_code` upsert，返回本地任务 ID/状态 |
| `get_contract_approval` | `GET /api/tools/get_contract_approval/{instance_id}` | 上游详情 + 本地任务/附件/状态 |
| `download_contract_attachment` | `POST /api/tools/download_contract_attachment` | body 含 `instance_id`、上游 `attachment_id`、`file_name` |
| `parse_contract_document` | `POST /api/tools/parse_contract_document` | body 含本地 `document_id` |
| `run_contract_rules` | `POST /api/tools/run_contract_rules` | body 含本地 `case_id` |
| `save_review_result` | `POST /api/tools/save_review_result` | upsert 该任务唯一审查结果 |
| `write_approval_comment` | `POST /api/tools/write_approval_comment` | body 含 `instance_id`、`review_id` |

同步路由交给 FastAPI 线程池执行。只有 `UpstreamClient` 能调用 `/mock-upstream/*`，不能直接读 Mock DB。

异步/管理路由：

- `POST /api/tasks/{task_id}/full-review` → 202，一键审查入队。
- `POST /api/tasks/{task_id}/retry` → 202，阻塞任务重试。
- `GET /api/tasks/{task_id}/status` → 轮询。
- `GET /api/tasks`、`GET /api/tasks/{task_id}`。
- `GET/POST/PUT/DELETE /api/admin/rules...`。

响应约定：

- 成功：`{"success": true, "data": ...}`。
- 任务级失败：HTTP 200 + `{"success": false, "error": {"code","message","stage","task_status","write_status"}}`。
- 未知 ID：404；表单非法：422；拉取级上游失败：502 `UPSTREAM_UNAVAILABLE`。

`UpstreamClient` 使用 `httpx.Client(timeout=..., trust_env=False)`，避免系统代理拦截 127.0.0.1。

## 4. 状态机与恢复

需求状态：`pending/parsing/reviewing/blocked/done`。不新增 `queued`，用 `pending + stage=queued`。

`stage`：`idle | queued | download | parse | review | save | write | done`。

| 事件 | task_status | stage | write_status |
|---|---|---|---|
| 新拉取 | `pending` | `idle` | `not_written` |
| 一键审查入队 | `pending` | `queued` | 不变 |
| worker 开始下载/解析 | `parsing` | `download` → `parse` | 不变 |
| 解析 success/partial | `reviewing` | `review` → `save` | 不变 |
| 开始回写 | `reviewing` | `write` | `writing` |
| 回写成功 | `done` | `done` | `success` |
| 任一阶段失败 | `blocked` | 失败阶段 | 回写失败时 `failed` |
| 人工重试入队 | `pending` | `queued` | 回写重试保持 `failed` 直到成功 |
| 启动恢复 | `blocked` | 失败阶段/`resume_stage` | `writing` → `failed` |

`resume_stage` 在入队时设置：新审查为 `download`，重试为失败阶段。重试时 `retry_count += 1`、清空 `last_error`。

重试映射：

- `download`：重新下载全部附件，再解析/审查/保存/回写。
- `parse`：解析现有主附件，再继续。
- `review`：重跑规则与结果生成，不重下载/解析。
- `save`：重新生成并保存结果，不重跑规则。
- `write`：复用现有 review/hits，只重写评论。

写状态：`not_written → writing → success|failed`；`failed → writing` 可重试；`success` 终态。只有 `write_status=success` 才是 `task_status=done`。

启动恢复 SQL（在 worker 启动前执行）：

```sql
UPDATE approval_tasks
SET task_status='blocked',
    stage=CASE WHEN stage='queued' THEN COALESCE(resume_stage,'download') ELSE stage END,
    write_status=CASE WHEN write_status='writing' THEN 'failed' ELSE write_status END,
    last_error_code='SERVICE_INTERRUPTED',
    last_error='service interrupted',
    updated_at=:now
WHERE task_status IN ('parsing','reviewing')
   OR write_status='writing'
   OR (task_status='pending' AND stage='queued');
```

对每个被修改任务写一条 `task_logs`。排队未开始的任务也转 blocked，因为内存队列无法跨重启恢复。

关闭时不提供硬取消；等待在途 `to_thread` 最多 `SHUTDOWN_GRACE_SECONDS=10`，未完成的由下次启动恢复。评论幂等键防止重复回写。

## 5. 规则引擎

匹配器接口：

```python
@dataclass
class RuleMatch:
    rule: Rule
    start: int
    end: int
    evidence_text: str
    position: dict
    matched_value: str | None = None

class Matcher(Protocol):
    mode: str
    def match(self, rule: Rule, document: TextDocument, parse: ParsedContract) -> RuleMatch | None: ...
```

`TextDocument.text` 是拼接后的全文，段映射把全局偏移转换成源位置。

| 模式 | `match_text` | 命中语义 | 证据 |
|---|---|---|---|
| `keyword` | 字符串 | 首次出现；拉丁文本忽略大小写 | 命中文本 + 前后窗口 |
| `all_keywords` | JSON 数组 | 所有关键词都出现 | 最早到最晚出现范围 |
| `regex` | 正则字符串 | 首次匹配，`re.MULTILINE|re.DOTALL` | 匹配范围 |
| `absence` | JSON 字符串数组 | 全都没出现才命中 | 文档级：`未检出相关表述：...` |
| `field_check` | JSON 对象 | 检查已解析字段 | 字段原文/位置；缺失时文档级 |
| `numeric_threshold` | JSON 对象 | 正则捕获数字，`Decimal` 比较 | 违规匹配范围 |

`field_check` 支持：

```json
{"fields":["party_a","party_b"],"op":"any_missing"}
{"field":"amount","op":"missing"}
{"field":"currency","op":"equals","value":"CNY"}
```

操作：`exists`、`missing`、`any_missing`、`equals`、`not_equals`、`in`。

`numeric_threshold` 示例：

```json
{
  "pattern":"(?:预付款|预付)[^。；\\n]{0,30}?(\\d+(?:\\.\\d+)?)\\s*%",
  "group":1,
  "op":"gt",
  "threshold":30,
  "unit":"%"
}
```

操作：`gt`、`gte`、`lt`、`lte`、`eq`、`between`（配 `upper`）。只用 `Decimal`，不用 float；遍历所有匹配，取第一个违规。

启用规则若 JSON/正则非法：记 `WARN` 并跳过，不阻塞合同。管理台保存时校验，拒绝非法启用规则。

证据与位置：

- 片段：命中前后各最多 60 字，压缩空白，截断处加省略号。
- PDF：`{"type":"pdf","page":2,"char_start":118,"char_end":174}`
- DOCX：`{"type":"docx","paragraph_index":7,"char_start":12,"char_end":58}`
- OCR：`{"type":"ocr","page":1,"line":3,"char_start":0,"char_end":24,"bbox":[x0,y0,x1,y1]}`
- 缺失/absence：`{"type":"document"}` + 人类可读说明。

汇总：

- 任一 high → high；否则任一 medium → medium；否则 low；无命中 → low。
- 命中按 high/medium/low、再按 `sort_order` 排序。
- `focus_points_json` 为字符串数组；每条命中一条，最多 8 条。
- `parse_status=partial` 时首条加 `解析完整度不足，请人工核对缺失字段。`
- 无命中时加 `未发现规则命中的重大风险，仍建议人工复核合同实质条款。`
- 摘要模板统计 high/medium/low 数量并点名最高风险。

种子规则（完整定义见 `references/rules.seed.json`，共 14 条）：

| Code | 类别 | 风险 | 模式 | 意图 |
|---|---|---|---|---|
| R001 | 预付款比例 | high | numeric_threshold | 预付款 > 30% |
| R002 | 付款周期 | medium | numeric_threshold | 账期 > 60 天 |
| R003 | 自动续约 | medium | keyword | `自动续约` |
| R004 | 违约责任 | medium | absence | 缺 `违约金/赔偿责任/违约责任` |
| R005 | 管辖地 | high | regex | 对方所在地法院管辖 |
| R006 | 主体信息缺失 | high | field_check | `party_a` 或 `party_b` 缺失 |
| R007 | 金额缺失 | high | field_check | `amount` 缺失 |
| R008 | 保密缺失 | medium | absence | 缺 `保密` |
| R009 | 数据处理 | medium | absence | 缺 `数据` 和 `个人信息` |
| R010 | 知识产权缺失 | medium | absence | 缺 `知识产权/著作权/专利` |
| R011 | 知识产权归属不利 | high | regex | 知识产权归对方 |
| R012 | 验收标准缺失 | medium | absence | 缺验收相关表述 |
| R013 | 合同期限缺失 | low | field_check | `expiry_date` 缺失 |
| R014 | 无限赔偿责任 | high | regex | 全部/一切/无限赔偿责任 |

## 6. 解析

### 主附件选择

1. 下载上游列出的所有附件。
2. 任一附件缺失/下载失败 → 任务 blocked。
3. 主附件 = 按上游 `sort_order` 第一个扩展名受支持（`pdf/docx/png/jpg/jpeg`）且非空的附件。
4. 标记 `is_primary=1`；其余附件只入库。
5. 主附件解析失败直接 blocked，不静默换第二个。

### 文本提取

**PDF**

- `pdfplumber.open`，逐页 `extract_text()`。
- 每页一个文本段，记录页内字符偏移。
- 总文本少于 `OCR_TEXT_MIN_CHARS`（建议 40）视为图片型 PDF，用 `pypdfium2` 以 200 DPI 渲染后 OCR。
- 部分页 OCR 成功、部分失败时保留成功文本并标 `partial`。

**DOCX**

- 按文档顺序遍历段落和表格；表格逐行扁平化为带段落索引的段。
- 位置 = `paragraph_index` + 字符偏移。
- 空文档或没有可用文本 → `failed`。

**图片**

- Pillow 读取，RapidOCR 识别。
- RapidOCR 懒加载单例 + `threading.Lock`（同一 ONNX session 并发不安全）。
- 按 OCR 行的 box 位置排序，段记录页、行、行内字符偏移和 bbox。

### 字段与条款

`basic_info_json`：

`contract_title`、`contract_no`、`party_a`、`party_b`、`amount`、`currency`、`effective_date`、`expiry_date`。

每个字段：

```json
{
  "value": "1200000",
  "raw_text": "合同金额：人民币 1,200,000 元",
  "position": {"type":"pdf","page":1,"char_start":200,"char_end":226},
  "status": "found"
}
```

状态：`found | missing | invalid`。

`clause_info_json`：

`payment`、`delivery`、`acceptance`、`breach`、`confidentiality`、`data`、`intellectual_property`、`dispute_resolution`。

每类条款包含 `value`（标题/名称）、`raw_text`、`position`、`status`。

分段：

- 识别 `第一条 付款条款`、`一、付款`、`1. 付款` 等标题，以及已知条款词。
- 段正文从标题到下一个标题。
- 别名映射到 8 个必需 key。
- PDF/OCR 的换行保留为 `\n`，方便正则匹配。

字段抽取用容错标签正则（全角冒号、空格、OCR 插入空格）；金额归一化为十进制字符串；币种尽量归一为 `CNY/USD/EUR`。

### parse_status

- `success`：文本可用，8 个基本字段和 8 类条款都找到/有效，无 OCR 页失败。
- `partial`：文本可用，但至少一个字段/条款缺失或无效，或部分 OCR 页失败。继续规则审查。
- `failed`：文件不可读/损坏/加密、类型不支持、空文档、全部 OCR 失败、没有可用文本。

只有 `failed` 阻塞任务；`partial` 继续，缺失字段仍可触发 `field_check` 规则。`parse_error` 记录失败原因，`warnings_json` 记录 partial 警告。

## 7. Mock 上游

独立 DB，同进程，前缀 `/mock-upstream`。

接口：

- `GET /mock-upstream/health`
- `GET /mock-upstream/approvals/pending?limit=50`
- `GET /mock-upstream/approvals/{instance_id}`
- `GET /mock-upstream/approvals/{instance_id}/attachments/{attachment_id}/file`
  - `FileResponse` + `X-Checksum-SHA256`。
  - 缺失/不可用返回 404 `{"code":"ATTACHMENT_NOT_FOUND"}`。
- `POST /mock-upstream/approvals/{instance_id}/comments`
  - body：`{"content":"...","idempotency_key":"contract-review:APV-...:42"}`
  - 唯一键；重复返回已有评论 + `duplicate=true`。
- `GET /mock-upstream/approvals/{instance_id}/comments`
- `POST /mock-upstream/admin/attachments/{attachment_id}/restore`
  - `available=1`，用于演示重试成功。
- `POST /mock-upstream/admin/faults`
  - 对 `detail`、`download`、`comment` 注入 HTTP 错误。
- `POST /mock-upstream/admin/reset`

种子审批单：

| 审批单 | 附件 | 场景 | 预期 |
|---|---|---|---|
| `APV-2026-001` | `设备采购合同.pdf` + 次要 `报价单.pdf` | PDF 高风险、多附件 | 预付款 60%、账期 90 天、自动续约、对方管辖 → high |
| `APV-2026-002` | `技术服务合同.docx` | DOCX 中风险 | 账期 75 天、自动续约、保密缺失 → medium |
| `APV-2026-003` | `保密协议扫描件.png` | 纯图片 OCR、缺合同编号 | 无命中、partial、整体 low |
| `APV-2026-004` | `系统运维合同.docx` | 附件 `available=0` | 下载 blocked；restore 后重试成功 |

高风险 PDF 必须包含未命中的安全条款（违约、保密、数据、知识产权、验收），确保只触发预期规则。中风险 DOCX 避免触发高风险规则。低风险 PNG 除合同编号外字段齐全。

Mock 评论跨重启持久化；`idempotency_key` 唯一。restore 只翻转 `available`，本地重试重新下载并校验 SHA-256。

## 8. 异步流水线

- `asyncio.Queue[Job]`，`maxsize=100`。
- lifespan 启动 2 个 worker，最大并发 2。
- worker 取 job 后 `await asyncio.to_thread(run_pipeline_sync, job)`。
- `Job` 含 `task_id`、`resume_stage`、`retry_count`。
- `JobQueueManager._inflight: set[int]` + `asyncio.Lock` 防重复入队；终态后清除。
- 已完成任务返回 200 + 现有结果；阻塞任务要求走重试；进行中返回 202 + 当前状态。

流水线阶段：

1. 若从 `download` 或更早开始：拉详情、下载全部附件；任一失败 → blocked。
2. 选主附件；下载与校验已完成。
3. 解析主附件；`failed` → blocked；`success/partial` → 继续。
4. 跑规则并保存命中；非法规则跳过并告警。
5. 生成摘要/关注点/评论，可选 LLM 润色，保存结果。
6. 用幂等键 `contract-review:{approval_code}:{review_id}` 回写。
7. 置 `done/success/done`，写时间戳和日志。

异常统一转 blocked + 稳定错误码：
`MISSING_ATTACHMENT`、`DOWNLOAD_FAILED`、`CHECKSUM_MISMATCH`、`OCR_FAILED`、`EMPTY_DOCUMENT`、`PARSE_FAILED`、`UPSTREAM_UNAVAILABLE`、`SAVE_FAILED`、`COMMENT_WRITE_FAILED`、`SERVICE_INTERRUPTED`。

轮询响应：

`task_id`、`task_status`、`write_status`、`stage`、`retry_count`、`last_error_code`、`last_error`、`updated_at`、`terminal`。

Web 每 2 秒轮询，`done`/`blocked` 停止。

启动恢复在 worker 启动前执行。关闭时排队任务丢失，下次启动标 `SERVICE_INTERRUPTED`，需人工重试。

幂等回写：

- 本地已 `success` 直接短路，不再调用上游。
- 每次尝试使用同一幂等键。
- 上游已成功但超时，Mock 的重复键响应返回已有评论。
- `write` 阶段重试不重跑解析、规则、结果生成。

## 9. Web 控制台

无前端构建；Jinja2 服务端渲染 + `static/app.js` 的 `fetch`/轮询。

| 页面 | 路由 | 内容 |
|---|---|---|
| 待办列表 | `GET /web/pending` | 已拉取审批、附件数、任务/回写/阶段、筛选、拉取/一键审查/详情 |
| 拉取动作 | `POST /web/actions/pull` | 调用列表工具，展示去重数量 |
| 详情查看 | `GET /web/tasks/{id}/detail` | 审批信息、表单 JSON、附件列表、下载状态、校验值、缺失标记、下载按钮 |
| 解析结果 | `GET /web/tasks/{id}/parse` | 解析状态/错误、基本信息原文与位置、条款表、OCR 标记、解析按钮 |
| 规则命中 | `GET /web/tasks/{id}/hits` | 总风险、命中卡片（规则名、风险徽标、证据、可读位置、建议）、执行按钮 |
| 结果处理 | `GET /web/tasks/{id}/result` | 摘要、关注点、评论预览、回写状态、保存/回写/一键审查、轮询 |
| 规则管理 | `GET /web/admin/rules`、`/new`、`/{id}/edit` | 规则 CRUD、模式帮助、校验、启停；被引用规则不硬删 |
| 任务管理 | `GET /web/admin/tasks` | 全部任务、状态筛选、重试次数、最后错误、重试 |
| 日志查看 | `GET /web/admin/logs?task_id=&level=&type=` | 任务日志和评论尝试，分页 |
| Mock 管理 | `GET /web/admin/mock` | Mock 审批/附件/评论、恢复缺失附件、故障开关、重置演示 |

风险徽标：high 红、medium 琥珀、low 绿。所有用户/证据内容由 Jinja 自动转义。

## 10. 示例合同生成

`scripts/generate_samples.py` 生成：

- `apv_2026_001_purchase.pdf`：reportlab，中文字体，多页，埋入高风险条款和次要报价单 PDF。
- `apv_2026_002_service.docx`：python-docx，中风险条款。
- `apv_2026_003_scan.png`：Pillow 渲染的图片扫描件，除合同编号外字段齐全。
- `apv_2026_004_hidden.docx`：正常生成，但 Mock DB 中 `available=0`，restore 后可下载。
- `manifest.json`：预期解析状态、命中规则、总风险、SHA-256。

Windows 字体：

- 候选：`%WINDIR%\Fonts\simsun.ttc`、`msyh.ttc`、`simhei.ttf`。
- 可用 `CN_FONT_PATH` 覆盖。
- ReportLab：`.ttc` 用 `TTFont(..., subfontIndex=0)`。
- DOCX：同时设置 `font.name` 和 `w:eastAsia` 为 `宋体`。
- Pillow：`ImageFont.truetype(path, 34)`，A4 @ 200 DPI（`1654x2339`），高对比度，不加随机噪声，自动换行。

确定性：

- 固定内容、布局、元数据、日期。
- ReportLab 固定文档信息；DOCX 固定 core properties，排序 zip 条目并固定 ZIP 时间戳。
- PNG 固定尺寸、字体、颜色，不加随机噪声。
- 没有中文字体时显式失败。
- `--verify-ocr` 可选：生成后用 RapidOCR 验证关键标签。

初始化顺序：生成文件 → 初始化 Mock DB 与校验值 → 初始化本地 DB/规则。`scripts/init_db.py` 负责顺序，默认幂等，`--reset` 才清空。

## 11. 测试与演示

pytest marker：`unit`、`integration`、`e2e`、`ocr`。

规则测试：

- 6 种模式命中/不命中。
- 数值边界（`gt`、`between`、Decimal）。
- 非法正则/JSON 跳过。
- high > medium > low；无命中 low。
- absence/field_check 证据。
- 关注点与 partial 提示。

解析测试：

- PDF 文本层字段、页码/字符位置、条款分段。
- DOCX 段落位置。
- PNG OCR 路径、行/bbox、缺合同编号导致 partial。
- 空/损坏/不可读 → failed。
- partial 继续审查。

E2E（真实 uvicorn，临时端口）：

- 连续拉取两次：只建一次任务，去重数量正确。
- 下载校验 SHA-256。
- 成功路径：解析 → 规则 → 保存 → 回写；高风险结果和上游评论。
- 回写幂等：重复写只产生一条上游评论。
- 附件缺失：一键审查在下载阶段 blocked；restore 后重试到 done。
- 回写失败：Mock comment 故障 → blocked + `write_status=failed`；关闭故障后重试只重写；无重复评论。
- 并发防重：两次同时一键审查只入队一个。
- 启动恢复：构造 `parsing`/`writing` 状态，重启服务，任务变 `SERVICE_INTERRUPTED`，重试可用。
- LLM 回退：非法 LLM 地址，流水线仍用模板完成。
- 管理台规则 CRUD 与校验。

`TestClient` 用于路由/表单校验；`httpx.Client` 对真实服务器做回环 E2E。测试 fixture 使用临时 `UPSTREAM_BASE_URL` 和独立 DB 路径，不污染演示数据。

`scripts/demo_closed_loop.py`：

1. 启动或连接服务。
2. 连续拉取两次并打印去重结果。
3. 审查高风险 PDF，轮询到 done。
4. 审查中风险 DOCX。
5. 审查扫描 PNG，展示 OCR/partial/low。
6. 审查失败单，展示 blocked。
7. restore Mock 附件后重试。
8. 重复回写，证明幂等。
9. 打印最终任务表和 Mock 评论数。

任何预期不符时非零退出。`docs/TOOLS.md` 记录签名、ID、请求/响应示例、错误结构和同步/异步区别；`README.md` 给出 Windows 快速启动。

## 12. 依赖与运行

`requirements.txt` 基线：

```text
fastapi
uvicorn[standard]
jinja2
httpx
pydantic-settings
python-multipart
pdfplumber
python-docx
rapidocr-onnxruntime
onnxruntime
numpy
Pillow
pypdfium2
reportlab
pytest
pytest-asyncio
```

安装成功后冻结实际版本。安装命令：

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -U pip -i https://pypi.org/simple
.venv/Scripts/python.exe -m pip install -r requirements.txt -i https://pypi.org/simple
```

运行：

```bash
.venv/Scripts/python.exe scripts/init_db.py
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

入口 `http://127.0.0.1:8000/web/pending`；API 文档 `/docs`。

## 13. 风险与需求冲突

1. **需求没有 `queued` 状态**：用 `pending + stage=queued`，文档和 UI 一致使用。
2. **回写失败重试**：需求说重试进入 `parsing/reviewing`，本方案从 `write` 阶段继续，避免重复审查；这是有意偏离。
3. **回写期间任务状态**：无 `writing` 任务状态，保持 `reviewing` + `write_status=writing` + `stage=write`。
4. **附件 ID 歧义**：下载工具 `attachment_id` 是上游 ID；解析工具 `document_id` 是本地 `approval_attachments.id`，必须在文档中写明。
5. **“第一个可解析附件”**：实现为第一个受支持且非空附件；解析失败不回退。如业务要求回退，需显式修改。
6. **任一附件缺失都会阻塞**：即使主合同已下载成功，也按锁定决策阻塞。
7. **回环 HTTP 依赖**：服务必须真实监听 `UPSTREAM_BASE_URL`；`TestClient` 不能覆盖适配层，E2E 必须启动真实服务器。
8. **OCR 精度**：RapidOCR 可能误读中文标点、金额、日期；样例图需清晰。OCR 单例加锁会限制 OCR 密集任务的并发。
9. **重依赖**：RapidOCR 拉入 ONNX Runtime、OpenCV、NumPy 和模型，安装体积大；镜像必须用官方 PyPI。
10. **版本漂移**：首次安装成功后冻结版本并重新验证样例哈希。
11. **Windows 字体**：PDF/PNG 依赖系统字体；没有字体时显式失败，不静默生成乱码。
12. **SQLite 并发**：WAL + 短连接可缓解，但只支持单进程；扩展需外部队列/worker。
13. **无认证**：管理端和 Mock 端无鉴权，只绑定 127.0.0.1，作为演示/内部工具。
14. **LLM 隐私**：默认关闭；开启时只发送派生摘要/命中项，不发送合同全文，README 中说明。
15. **历史规则一致性**：命中保存规则快照，避免改规则影响历史结果。
16. **重启恢复**：排队任务也转 blocked，需要人工重试；不做自动重放。

## 实施顺序

1. 脚手架：config、paths、常量、SQLite schema、init 脚本。
2. 生成样例文件，种子 Mock/规则。
3. Mock 路由、Mock DB、restore/fault、UpstreamClient。
4. 拉取/附件 + 7 个同步工具/路由。
5. PDF/DOCX/OCR 解析与位置映射。
6. 规则匹配器、种子规则、结果模板、保存/回写。
7. 可恢复流水线、队列 worker、启动恢复、状态 API。
8. 5 个业务页面 + 管理台。
9. 测试、README、工具文档、闭环演示。
10. 跑通 E2E，校准 OCR/样例。

## 关键文件

- `app/schema.sql`
- `app/services/tool_functions.py`
- `app/services/pipeline.py`
- `app/services/rules/engine.py`
- `app/services/parser/service.py`
- `app/services/mock_upstream/router.py`
- `scripts/init_db.py`
- `scripts/generate_samples.py`
- `tests/test_pipeline_e2e.py`
