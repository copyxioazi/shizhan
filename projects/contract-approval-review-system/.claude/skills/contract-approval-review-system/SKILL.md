---
name: contract-approval-review-system
description: 按 2.4 需求从零搭建可运行的合同审批审查系统（FastAPI + SQLite + PDF/DOCX/OCR + 数据驱动规则引擎 + Mock 审批系统 + Web 控制台）。Use when the user asks to build/implement 合同审批审查系统、合同审查系统、contract approval review, or similar.
---

# 合同审批审查系统构建指南

## 何时使用

当用户要求实现 `合同审批审查系统.md` 的 2.4 需求，或要求搭建“合同审批 + 自动审查 + 风险评论回写”闭环时使用。

- 输入：需求 md、可写的项目目录。
- 输出：可运行服务、数据库初始化脚本、示例合同、工具调用说明、完整闭环演示、测试。
- 开始前先读 `references/decisions.md`（锁定决策）和 `references/architecture.md`（完整设计）。
- 如果仓库已有代码，先适配现有结构，不要盲目覆盖。

## 不可协商的决策

1. **交付形态**：FastAPI REST 工具服务 + 服务端渲染 Web 控制台；不做 MCP，不引入前端构建。
2. **上游审批系统**：内置 Mock，同一个 FastAPI 进程，挂在 `/mock-upstream/*`；适配层通过 `http://127.0.0.1:8000` HTTP 回环调用，保留真实 API 边界。
3. **解析与 OCR**：`pdfplumber` 读 PDF 文本层，`python-docx` 读 DOCX，`rapidocr-onnxruntime` 识别扫描件；纯离线。
4. **规则引擎**：规则全部存 DB，管理台可增删改；支持 6 种 `match_mode`：`keyword`、`all_keywords`、`regex`、`absence`、`field_check`、`numeric_threshold`。
5. **LLM**：仅润色中文摘要、审批关注点和评论文案；默认关闭，OpenAI 兼容接口，失败回退模板，不发送合同全文。
6. **失败语义**：附件缺失、下载失败、OCR 失败、空文档、上游接口失败 → 任务 `blocked` 并记录失败阶段；回写失败 → `write_status=failed` 且任务 `blocked`；人工重试从失败阶段继续，回写幂等。
7. **执行方式**：7 个工具函数保持同步签名；只有“一键审查”异步入队，页面轮询状态。
8. **后台机制**：进程内 `asyncio.Queue` + 2 个 worker，阻塞解析/OCR 用 `asyncio.to_thread` 执行；不引入 Celery/Redis。
9. **重启恢复**：启动时把停留在 `parsing`/`reviewing`/`writing` 的任务标记 `blocked`，原因 `SERVICE_INTERRUPTED`，人工重试。
10. **多附件**：审批单可有多个附件，但只审查按 `sort_order` 排序的第一个可解析合同附件（主附件）；其余附件只下载入库。
11. **ID 语义**：`instance_id = approval_code`，`case_id = approval_tasks.id`，`document_id = approval_attachments.id`；`approval_code` 唯一，作为去重键。
12. **种子数据**：4 个审批单——PDF 高风险（多附件）、DOCX 中风险、扫描 PNG 低风险/字段缺失、附件缺失失败单；14 条规则覆盖需求要求的 11 类。
13. **数据库**：SQLite，使用标准库 `sqlite3`；8 张必需表保留需求列名，只做最小扩展。本地库执行 `references/schema.sql`，Mock 库执行 `references/mock_schema.sql`，两个库物理隔离。
14. **交付物**：服务、`init_db.py`、示例合同、`docs/TOOLS.md`、闭环演示脚本、pytest 测试。

## 交付物与验收映射

| 需求 | 必须交付 |
|---|---|
| 2.4.1 接入 | 待办拉取、附件下载、按 `approval_code` 去重 |
| 2.4.2 角色 | 审批系统（Mock）、法务审核人（Web）、系统管理员（规则/日志/重试） |
| 2.4.3 服务入口 | 7 个工具函数 + REST 路由 |
| 2.4.4 状态 | `pending/parsing/reviewing/blocked/done`；`not_written/writing/success/failed` |
| 2.4.5 解析字段 | 8 个基本信息 + 8 类条款，每项带原文、位置、提取状态 |
| 2.4.6 规则 | 14 条种子规则，输出总风险、命中证据、建议、关注点 |
| 2.4.7 调用端 | 待办、详情、解析、命中、结果处理 5 个模块 |
| 2.4.8 服务模块 | 拉取、附件、解析、规则、回写、日志 |
| 2.4.9 数据表 | 8 张表，见 `references/schema.sql` |
| 2.4.10 工具接口 | 7 个签名，见下 |
| 2.4.11 输出格式 | 低/中/高、命中数组、中文摘要、关注点数组、回写内容 |
| 2.4.12 验收 | 去重、下载、OCR、规则、回写、阻塞重试、完整闭环 |

7 个工具签名（保持同步 `def`）：

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

## 环境与依赖

当前机器事实：

- 解释器：项目使用的 Python 3.11+，需带 pip、可建 venv。
- 如本机 pip 镜像不可用，所有安装命令显式加 `-i https://pypi.org/simple`。
- 中文字体已存在：`%WINDIR%\Fonts\msyh.ttc`、`simsun.ttc`、`simhei.ttf`。
- 项目目录：`<project-root>`。

安装与启动（Git Bash）：

```bash
cd <project-root>
python -m venv .venv
.venv/Scripts/python.exe -m pip install -U pip -i https://pypi.org/simple
.venv/Scripts/python.exe -m pip install -r requirements.txt -i https://pypi.org/simple
.venv/Scripts/python.exe scripts/init_db.py
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

依赖基线（首次安装成功后冻结实际版本）：

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

## 推荐目录结构

```text
app/
├─ main.py                 # create_app、lifespan、路由注册、恢复、worker
├─ config.py               # 环境变量、路径、开关
├─ db.py                   # sqlite3 连接、事务、WAL、busy_timeout
├─ schema.sql
├─ status.py               # 状态/阶段/错误码常量
├─ api/{tools,tasks,admin}.py
├─ web/{routes,viewmodels}.py
├─ services/
│  ├─ tool_functions.py    # 7 个同步工具
│  ├─ upstream_client.py   # 唯一允许调用 /mock-upstream/* 的组件
│  ├─ approvals.py
│  ├─ attachments.py
│  ├─ parser/{service,pdf_parser,docx_parser,ocr,fields,sections,text_document}.py
│  ├─ rules/{engine,matchers,validator}.py
│  ├─ review.py
│  ├─ llm.py
│  ├─ comments.py
│  ├─ pipeline.py
│  ├─ queue.py
│  └─ logs.py
├─ mock_upstream/{router,service,seed,schema.sql}
├─ seed/rules.json
├─ templates/
└─ static/{app.js,style.css}
scripts/{init_db,generate_samples,reset_demo,demo_closed_loop}.py
sample_contracts/
data/
docs/{TOOLS,ARCHITECTURE,DEMO}.md
tests/
```

## 实施顺序

1. 脚手架：`config.py`、`db.py`、`schema.sql`、`init_db.py`。
2. 生成 4 类示例合同，初始化 Mock DB、本地 DB、14 条规则。
3. 实现 `/mock-upstream/*`、`upstream_client.py`、附件 restore/fault 接口。
4. 实现拉取/下载/去重和 7 个同步工具 + REST 路由。
5. 实现 PDF/DOCX/OCR 解析、字段与条款抽取、位置映射。
6. 实现 6 种规则匹配、风险汇总、结果模板、保存与幂等回写。
7. 实现可恢复流水线、队列 worker、启动恢复、状态轮询 API。
8. 实现 5 个业务页面 + 管理台（规则、任务、日志、Mock）。
9. 实现 pytest 单元/集成/E2E、`docs/TOOLS.md`、闭环演示脚本。
10. 跑通全链路，校准样例合同与 OCR。

## 关键实现约束

### 状态机

需求没有 `queued` 状态，用 `pending + stage=queued` 表示排队。`stage` 取值：
`idle | queued | download | parse | review | save | write | done`。

| 事件 | task_status | stage | write_status |
|---|---|---|---|
| 新拉取 | `pending` | `idle` | `not_written` |
| 一键审查入队 | `pending` | `queued` | 不变 |
| 开始下载/解析 | `parsing` | `download` → `parse` | 不变 |
| 解析 success/partial | `reviewing` | `review` → `save` | 不变 |
| 开始回写 | `reviewing` | `write` | `writing` |
| 回写成功 | `done` | `done` | `success` |
| 任一阶段失败 | `blocked` | 失败阶段 | 回写失败时 `failed` |
| 人工重试 | `pending` | `queued` | 回写重试保持 `failed` 直到成功 |
| 启动恢复 | `blocked` | 失败阶段/`resume_stage` | `writing` → `failed` |

重试映射：`download` → 重新下载全部附件；`parse` → 解析现有主附件；`review` → 重跑规则；`save` → 重新生成并保存结果；`write` → 只重写评论，不重解析。

### 规则匹配

| match_mode | match_text | 命中语义 |
|---|---|---|
| `keyword` | 字符串 | 首次出现；英文忽略大小写 |
| `all_keywords` | JSON 数组 | 所有关键词都出现 |
| `regex` | 正则字符串 | 首次匹配，`MULTILINE|DOTALL` |
| `absence` | JSON 关键词数组 | 全都没出现才命中 |
| `field_check` | JSON 对象 | 检查解析字段存在/缺失/等值 |
| `numeric_threshold` | JSON 对象 | 正则捕获数字，用 `Decimal` 与阈值比较 |

14 条种子规则见 `references/rules.seed.json`，覆盖：预付款比例、付款周期、自动续约、违约责任、管辖地、主体缺失、金额缺失、保密缺失、数据处理、知识产权、验收标准缺失，另加合同期限、无限赔偿责任。

证据：命中位置前后各 60 字，压缩空白；风险汇总 `high > medium > low`，无命中为 `low`；关注点每条命中一条，最多 8 条；`parse_status=partial` 时首条加“解析完整度不足，请人工核对缺失字段”。

### 解析

- `basic_info_json`：`contract_title/contract_no/party_a/party_b/amount/currency/effective_date/expiry_date`。
- `clause_info_json`：`payment/delivery/acceptance/breach/confidentiality/data/intellectual_property/dispute_resolution`。
- 每个字段：`{value, raw_text, position, status}`；`status ∈ found|missing|invalid`。
- 位置：PDF `{type:"pdf",page,char_start,char_end}`；DOCX `{type:"docx",paragraph_index,char_start,char_end}`；OCR `{type:"ocr",page,line,char_start,char_end,bbox}`；缺失字段 `{type:"document"}`。
- `parse_status`：`success`（字段/条款齐全）、`partial`（有缺失但仍可审查）、`failed`（不可读/空/全部 OCR 失败）。`partial` 继续审查，`failed` 才 `blocked`。

### Mock 上游

- `GET /mock-upstream/approvals/pending?limit=50`
- `GET /mock-upstream/approvals/{instance_id}`
- `GET /mock-upstream/approvals/{instance_id}/attachments/{attachment_id}/file`
- `POST /mock-upstream/approvals/{instance_id}/comments`（幂等键）
- `GET /mock-upstream/approvals/{instance_id}/comments`
- `POST /mock-upstream/admin/attachments/{attachment_id}/restore`（恢复缺失附件，让重试成功）
- `POST /mock-upstream/admin/faults`（detail/download/comment 故障注入）
- `POST /mock-upstream/admin/reset`

### 异步流水线

- `asyncio.Queue(maxsize=100)`，2 个 worker，`asyncio.to_thread(run_pipeline_sync)`。
- `_inflight: set[int]` + `asyncio.Lock` 防止同一任务重复入队。
- 一键审查：`POST /api/tasks/{id}/full-review` → 202；重试：`POST /api/tasks/{id}/retry` → 202。
- 轮询：`GET /api/tasks/{id}/status` 返回状态、阶段、错误、重试次数、`terminal`。
- 错误码：`MISSING_ATTACHMENT`、`DOWNLOAD_FAILED`、`CHECKSUM_MISMATCH`、`OCR_FAILED`、`EMPTY_DOCUMENT`、`PARSE_FAILED`、`UPSTREAM_UNAVAILABLE`、`SAVE_FAILED`、`COMMENT_WRITE_FAILED`、`SERVICE_INTERRUPTED`。
- 回写幂等键：`contract-review:{approval_code}:{review_id}`；本地已 `success` 直接短路。

### LLM（可选）

环境变量：`LLM_ENABLED=false`、`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_TIMEOUT_SECONDS=15`。只在规则命中后发送派生摘要/命中项，不发送合同全文；任何异常回退模板，并记录 `llm_enhanced=0`。

## 种子数据与演示

| 审批单 | 附件 | 场景 | 预期 |
|---|---|---|---|
| `APV-2026-001` | `设备采购合同.pdf` + `报价单.pdf` | 预付款 60%、账期 90 天、自动续约、对方管辖 | high |
| `APV-2026-002` | `技术服务合同.docx` | 账期 75 天、自动续约、保密缺失 | medium |
| `APV-2026-003` | `保密协议扫描件.png` | 纯图片 OCR、缺合同编号 | low + partial |
| `APV-2026-004` | `系统运维合同.docx` | Mock 附件 `available=0` | blocked，restore 后重试成功 |

样例生成：`reportlab`（PDF）、`python-docx`（DOCX）、`Pillow`（PNG），中文字体用系统字体；生成脚本必须确定性，并在 `manifest.json` 记录预期命中与 SHA-256。

## 常见坑

1. 需求没有 `queued` 状态，不要新增；用 `pending + stage=queued`。
2. 回写超时但上游已成功时，用幂等键让 Mock 返回已有评论，避免重复。
3. RapidOCR 的 ONNX session 并发不安全；用懒加载单例 + `threading.Lock`。
4. DOCX 没有可靠页码；位置用段落索引 + 字符偏移。
5. `httpx.Client(..., trust_env=False)`，避免本机代理拦截 127.0.0.1 回环。
6. Windows 下 DOCX/PDF 的元数据和 zip 时间戳会影响确定性；固定元数据并排序 zip 条目。
7. ReportLab 加载 `.ttc` 需要 `subfontIndex=0`；没有中文字体要显式失败。
8. PDF 文本层字符数过少（如 <40）时要转 OCR，不能直接当空文档。
9. 规则 JSON/正则非法时应跳过并记 `WARN`，不能让整单失败。
10. 规则命中要保存规则名/等级/建议快照，避免后台改规则影响历史结果。

## 验收命令

```bash
.venv/Scripts/python.exe scripts/init_db.py
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe scripts/demo_closed_loop.py
```

Web 入口：`http://127.0.0.1:8000/web/pending`；API 文档：`http://127.0.0.1:8000/docs`。

验收必须覆盖：

- 连续拉取两次，只创建一次任务。
- 附件下载并保存 SHA-256。
- PDF、DOCX、扫描 PNG 均能解析出字段。
- 规则命中包含风险等级、证据、位置、建议。
- 保存结果并写回 Mock 评论区。
- 附件缺失进入 `blocked`；restore 后重试到 `done`。
- 回写失败进入 `blocked + write_status=failed`；恢复后重试只重写。
- 服务重启后中间态变 `blocked`，人工重试可继续。

## 参考文件

- `references/decisions.md` — 访谈锁定决策与冲突处理规则。
- `references/architecture.md` — 完整设计：目录、表结构、状态机、规则、解析、Mock、异步、Web、样例、测试、风险。
- `references/schema.sql` — 本地库 8 张必需表 + 最小扩展字段。
- `references/mock_schema.sql` — Mock 上游库 4 张表（单独执行）。
- `references/rules.seed.json` — 14 条种子规则。
