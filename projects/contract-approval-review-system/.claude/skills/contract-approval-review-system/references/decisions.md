# 锁定决策

本文件记录需求访谈中用户确认的决策。实现时如果本文与 `architecture.md` 或需求文档冲突，**以本文为准**；如需偏离，先向用户说明差异。

## 产品与交付

### D1. 交付形态：REST + Web 控制台

- FastAPI 暴露 7 个工具 REST 接口。
- 内置服务端渲染 Web 控制台，覆盖 2.4.7 的五个模块：待办、详情、解析结果、规则命中、结果处理。
- 不做 MCP，不引入 React/Vue 或前端构建步骤。
- 理由：闭环演示最直接，一条命令可跑；工具签名仍与需求一致。

### D2. 上游审批系统：内置 Mock + 适配层

- 当前没有真实审批系统接口。
- 自带 Mock 审批系统：待办、详情、附件、评论区、故障注入。
- 适配层抽象为 `UpstreamClient`，未来可切换真实系统。
- 理由：保证本地可完整闭环，同时保留真实 API 边界。

### D3. Mock 运行形态：同进程 HTTP 回环

- Mock 路由挂在同一个 FastAPI 进程的 `/mock-upstream/*`。
- `UpstreamClient` 通过 `http://127.0.0.1:8000` 调用，不直接读 Mock DB。
- 理由：只需启动一个进程，又能真实验证 HTTP 适配层。
- 注意：`httpx.Client` 使用 `trust_env=False`，避免系统代理拦截回环。

### D4. 解析与 OCR：本地真实解析

- PDF 文本层：`pdfplumber`。
- DOCX：`python-docx`。
- 扫描件/无文本层 PDF：`rapidocr-onnxruntime`，离线运行。
- 无文本层 PDF 用 `pypdfium2` 渲染成图片后 OCR。
- 理由：满足“解析文档和图片扫描件”的验收，不依赖云服务。
- 风险：RapidOCR 安装体积较大；OCR 结果可能有少量识别误差，样例文件需保持清晰。

### D5. LLM：规则为主，可选润色

- 审查结论由确定性规则引擎产生，LLM 不参与风险判定。
- LLM 仅润色中文摘要、审批关注点和评论文案。
- 默认关闭，通过环境变量开启；任何失败回退模板。
- 不发送合同全文，只发送派生摘要和命中项。
- 理由：保证可复现、离线可跑、无需 API Key；保留扩展能力。

## 规则与行为

### D6. 规则引擎：全数据驱动

- 规则存 `review_rules`，管理台可增删改、启停。
- `match_mode` 支持：`keyword`、`all_keywords`、`regex`、`absence`、`field_check`、`numeric_threshold`。
- 数值阈值等参数以 JSON 存在 `match_text`。
- 非法 JSON/正则的启用规则跳过并记 `WARN`，不让整单失败。
- 理由：满足“维护规则”的管理员角色，避免特殊规则散落在代码里。

### D7. 失败与重试：统一 blocked + 分阶段重试

- 附件缺失、下载失败、校验失败、OCR 失败、空文档、上游接口失败 → 任务 `blocked`，记录失败阶段和错误码。
- 回写失败 → `write_status=failed` 且任务 `blocked`。
- 人工重试从失败阶段继续：
  - `download`：重新下载全部附件。
  - `parse`：解析现有主附件。
  - `review`：重跑规则。
  - `save`：重新生成并保存结果。
  - `write`：只重写评论，不重解析。
- 回写幂等键：`contract-review:{approval_code}:{review_id}`。
- 理由：避免重复审查和重复评论，同时让阻塞原因可见、可恢复。

### D8. 执行方式：7 个工具同步 + 一键审查异步

- `list_pending_contract_approvals` 等 7 个工具保持同步 `def`，与需求签名一致。
- Web/API 的“一键审查”把完整流水线放入后台队列，HTTP 202 返回，页面轮询。
- 理由：工具接口可被脚本逐步调用；Web 端又不会因 OCR 长时间阻塞请求。

### D9. 后台机制：进程内 asyncio 队列 + 线程池

- `asyncio.Queue(maxsize=100)`。
- 2 个 worker，最大并发 2。
- 阻塞的解析/OCR/HTTP 用 `asyncio.to_thread` 执行。
- 同一任务通过 `_inflight` 集合防止重复入队。
- 不使用 Celery/Redis/独立 worker 进程。
- 理由：单机演示零额外服务，状态全部落 SQLite。

### D10. 重启恢复：中间态转 blocked

- 启动时扫描 `parsing`、`reviewing`、`writing` 中停留的任务，以及已排队未开始的 `pending + stage=queued`。
- 统一置 `blocked`，错误码 `SERVICE_INTERRUPTED`。
- 回写中的任务把 `write_status` 置 `failed`。
- 由人工点击重试继续，不自动重新入队。
- 理由：避免重复调用上游/重复回写；状态不会卡死。

## 数据与范围

### D11. 多附件：主附件审查

- 一个审批单可以有多个附件。
- 按 Mock 上游 `sort_order` 取第一个扩展名受支持且非空的附件作为主合同。
- 其余附件只下载、校验、入库，不参与审查。
- `contract_parses` 保持每个 `task_id` 一行。
- 主附件解析 `failed` 时任务 `blocked`，不静默切换到第二个附件。
- 理由：与需求表结构一致，避免字段冲突和证据定位混乱。

### D12. ID 语义：复用现有主键

- `instance_id = approval_code`（审批编号，唯一业务标识）。
- `case_id = approval_tasks.id`。
- `document_id = approval_attachments.id`。
- 下载工具的 `attachment_id` 是 Mock 上游的附件 ID；解析工具的 `document_id` 是本地 `approval_attachments.id`。
- 去重唯一键：`approval_code`。
- 理由：与需求表结构一一对应，减少映射层。

### D13. 数据库：SQLite + 标准库 sqlite3

- 本地库 `data/app.db`，Mock 库 `data/mock_upstream.db`，物理隔离。
- 使用 WAL、`busy_timeout=5000`、短连接；OCR/HTTP 不放在数据库事务内。
- 8 张必需表保留需求列名，只增加 `stage/resume_stage/retry_count/last_error/sha256/is_primary` 等必要字段。
- 不做 ORM 迁移框架；`scripts/init_db.py` 负责建表与种子。
- 理由：零外部服务、可重复初始化、演示稳定。

### D14. 种子数据：4 个审批单

- `APV-2026-001`：PDF 高风险，主附件 + 次附件。
- `APV-2026-002`：DOCX 中风险。
- `APV-2026-003`：扫描 PNG，低风险、部分字段缺失，演示 OCR 和 `partial`。
- `APV-2026-004`：附件缺失，演示 `blocked`；Mock restore 后重试成功。
- 14 条规则覆盖需求要求的 11 类风险。
- 理由：既覆盖成功路径，又能直观演示阻塞、重试、去重。

### D15. 交付边界

- 本次先交付“系统构建指南” skill，不直接实现系统。
- skill 安装位置：项目级 `<project-root>\.claude\skills\contract-approval-review-system\`。
- skill 用途：触发后按本文和 `architecture.md` 从零搭建可运行系统。
- agent 设计与已确认决策冲突时，以本文件为准。

## 与需求文档的已知差异

| 差异 | 处理 |
|---|---|
| 需求没有 `queued` 状态 | 用 `pending + stage=queued`，不新增枚举 |
| 需求说重试后进入 `parsing` 或 `reviewing` | 实际从失败阶段继续；回写失败只重写，避免重复审查 |
| 需求没有 `writing` 任务状态 | 回写期间 `task_status` 保持 `reviewing`，用 `write_status=writing` + `stage=write` 表达 |
| `attachment_id` / `document_id` 含义相近 | 明确：前者是上游 ID，后者是本地附件主键 |
| 附件缺失失败语义 | 任一附件缺失都阻塞，即使主合同已下载成功 |
| 无认证 | 仅绑定 127.0.0.1 作为内部演示工具；上线需另加认证 |

## 环境事实

- Python：3.11+，带 pip，可建 venv。
- 安装依赖时如本机镜像不可用，显式使用 `-i https://pypi.org/simple`。
- 中文字体：Windows 系统字体目录下的 `msyh.ttc`、`msyhbd.ttc`、`simsun.ttc`、`simhei.ttf`、`simkai.ttf`。
- 本项目不需要前端构建。
