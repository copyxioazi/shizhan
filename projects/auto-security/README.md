# 自动化安全评估系统（项目骨架）

基于 [`项目需求.md`](项目需求.md) **v1.3** 搭建的前后端骨架。系统在 Linux VM 的 Docker 沙箱中完成环境检查、代码分析、漏洞验证、攻击路径整理与报告输出，并通过 WebSocket 实时展示阶段、角色、日志与资源变化。

> 仅用于本机演示与课程/项目交付，不应直接用于生产环境。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | React 18 + Vite + TypeScript + Ant Design 5 + React Router 6 + Zustand + ECharts |
| 后端 | FastAPI + SQLAlchemy 2.x（async）+ Pydantic v2 + PyJWT + bcrypt |
| 数据库 | PostgreSQL 16（Linux VM 上的 Docker Compose） |
| 沙箱 | Linux VM 上的 Docker 容器，后端通过 SSH 连接 Docker Engine |
| 源码同步 | tar over SFTP，任务前后 SHA-256 指纹校验 |

## 当前实现状态

已实现并可直接联调的部分：

- 认证：初始化、登录、当前用户、系统状态；JWT 24 小时；bcrypt cost 12。
- 项目：创建、列表、详情、启动、停止、删除、阶段与角色任务查询。
- 调度：四阶段串行推进、角色串行执行、阶段超时、停止取消、启动对账、并发限制。
- 沙箱：源码同步到 VM、只读挂载、固定安全参数、命令白名单、超时与输出截断、资源统计、孤儿容器清理。
- 执行能力：关键字搜索、逐条命令审计、1 GB 工作区配额、验证代码语法检查、上一轮容器清理、磁盘空间致命检查。
- 规则引擎：5 类检测规则（SQL 注入、命令注入、路径穿越、IDOR、硬编码密钥），确定性输出。
- LLM 多角色：general / code_analyst / vuln_verifier / report_writer 走 OpenAI 兼容接口，输出经 Pydantic Schema 校验；失败后本轮剩余阶段自动切换规则引擎。
- 角色：6 类角色全部落地；分析、验证、攻击路径、报告生成形成闭环。
- 结果：漏洞列表/详情、攻击路径、Markdown + 自包含 HTML 报告、下载。
- 监控：日志、聊天消息、资源采样、8 类 WebSocket 消息、快照、心跳与退避重连。
- 配置：管理员在线读取/更新配置，API Key 脱敏。
- 前端：第 12 章全部页面与路由守卫。
- 示例项目：`examples/vuln-demo` 内置 5 类漏洞与 4 个验证脚本。

尚未完成 / 不在本期范围：

- `local` 本机沙箱：按需求列为 P2，仅保留枚举与配置。
- Git 仓库接入、PDF 报告、用户注册/管理：按需求 D-01～D-06 不在本期范围。
- 浏览器端未做 E2E 自动化；已验证后端单测、应用导入/OpenAPI、前端 `tsc` 与生产构建，并在当前 VM 环境跑通完整演示链路。

### 执行能力细化项

- 关键字搜索（FR-EXEC-03）：任务说明词项 + 内置安全关键字，经沙箱 `helper.py search` 执行；单关键字 200 条、总量 1000 条上限，命中写入运行日志。
- 逐条命令审计（FR-EXEC-05）：每次 `exec`/`helper` 写入 `runtime_logs`，包含命令、工作目录、退出码、耗时与输出摘要；helper 输出只记录字节数，避免源码/凭据进入日志。
- 1 GB 工作区配额（FR-EXEC-06）：命令由沙箱 `helper.py run` 托管，20 ms 轮询 `/workspace` 占用并设置 `RLIMIT_FSIZE=1 GB`；超限杀死整个进程组、返回 125，记录 `error` 并中止后续命令；任务完成前清空 `tmp/`。
- 验证代码语法检查（FR-VULN-03）：执行前用 `ast.parse` 只读检查，不生成 `.pyc`；语法错误记为 `failed` 并写入证据。
- 环境检查（FR-ENV-05）：VM 工作区可用磁盘不足 1 GB 时判定为致命失败。
- 环境生命周期（FR-ENV-04）：项目再次启动时先销毁上一轮容器，保留上一轮 VM 工作区。
- 默认隔离类型（FR-CONF-05）：新建项目未显式指定时读取 `isolation.default_type`。

## 编排与工具层

调度器与 worker 之间有两层显式边界：

- `app/orchestration/state.py`：`RunState` 是本轮运行的内存视图，包含阶段、角色、计划、发现、工具轨迹与 token 数；数据库仍是事实来源，状态对象不负责持久化。
- `app/tools/`：worker 不再直接拼 `helper.py` 参数，而是调用 `ToolExecutor`（`list_files`、`read_file`、`search_code`、`syntax_check`、`run_command`）或 `ToolRegistry`（仅暴露给模型的安全工具）。路径校验、命令白名单、超时、配额与审计仍由 `SandboxRuntime` 强制执行。

当前项目已把“换管道、不换行为”的职责边界抽出来：四阶段调度、结果和验收标准保持不变，并在 `RunState` 与工具执行层之上接入了可选的 LangGraph 引擎。

### ReAct 代码分析（P0）

`orchestration.analysis_mode` 控制 `code_analyst` 的执行方式：

| 值 | 行为 |
|---|---|
| `one_shot`（默认） | 一次性把源码交给模型，保持 v1.3 的确定性行为 |
| `react` | 模型通过 OpenAI tool calling 自行选择 `list_files` / `read_file` / `search_code` / `syntax_check`，多轮调查后输出 JSON |

ReAct 模式的边界：

- 模型只能看到 `/src` 只读工具，`run_command` 不在模型工具列表中；
- 工具执行仍经过路径校验、白名单、超时、配额与审计；
- 受 `orchestration.react_max_steps`、`orchestration.react_max_tokens` 和
  `orchestration.react_tool_output_chars` 约束；token 预算在每次调用前检查，
  单次调用可能略微超出（例如预算 8,000、实际 8,380）；
- 轮次/token 预算耗尽时强制要求模型输出最终 JSON；
- 模型调用失败、输出非法或证据无法落地时，回退到规则引擎；
- 默认 `one_shot`，不影响既有验收。

在「系统配置 → 编排模式（Agent）」中切换，或调用：

```http
PUT /api/system/config
{"orchestration.analysis_mode": "react"}
```

`vuln-demo` A/B 实测（同一模型、同一示例）：

| 指标 | one_shot（项目 36） | react（项目 37） |
|---|---:|---:|
| code_analyst token | 2,827 | 8,380 |
| 全轮 token | 6,052 | 11,909 |
| 模型轮次 | 1 | 3 |
| 模型工具调用 | 0 | 7 |
| 读取文件数 | 9 | 6 |
| 漏洞 | 5（4 verified + 1 skipped） | 6（4 verified + 2 skipped） |
| 耗时 | 约 75 秒 | 约 100 秒 |

小仓库上 ReAct 的 token 约为 2 倍；它的价值主要体现在文件更多、需要多轮定位的项目。

### LangGraph 编排引擎（Step 3/4）

`orchestration.engine` 控制四阶段的执行方式：

| 值 | 实现 |
|---|---|
| `fixed`（默认） | [FixedOrchestrator](backend/app/orchestration/orchestrator.py) 串行循环 |
| `langgraph` | [LangGraphOrchestrator](backend/app/orchestration/orchestrator.py) 用 `StateGraph` 表达同样的四阶段固定流程 |

两种引擎共用同一组 `StageHooks`，因此数据库写入、WS 推送、日志、超时、失败语义完全一致；区别只在“谁驱动阶段循环”。

- 图结构：`START → environment_scan → code_analysis → vulnerability_verify → report_generate → END`
- 阶段失败：节点捕获 `StageAborted`，条件边直接到 `END`，由调度器统一写项目失败状态；
- 依赖：`langgraph==1.2.16`；未安装时自动回退 `fixed` 并写 warn 日志；
- 与 ReAct 组合：`orchestration.engine=langgraph` + `orchestration.analysis_mode=react` 可同时生效。

行为对齐实测：

| 配置 | 漏洞 | Token | 耗时 |
|---|---|---:|---:|
| `fixed` + `one_shot`（项目 38） | 5（4 verified + 1 skipped） | 5,752 | 约 75 秒 |
| `langgraph` + `one_shot`（项目 39） | 5（4 verified + 1 skipped） | 5,871 | 约 70 秒 |
| `langgraph` + `react`（项目 40） | 5（4 verified + 1 skipped），4 轮 / 8 次工具调用 | 13,320 | 约 90 秒 |

默认仍为 `fixed` + `one_shot`，不影响既有验收。

### 条件边与验证失败重规划（Step 5）

`langgraph` 引擎在固定四阶段之上增加了两条动态行为：

1. **无候选漏洞时跳过验证**
   `code_analysis` 完成后检查本轮漏洞数；为 0 时不进入 `vulnerability_verify`，
   将阶段标记为 `success` 并写“阶段跳过”日志后直接进入报告生成。
   `fixed` 引擎保持始终执行验证，行为不变。

2. **验证失败重规划**
   `vuln_verifier` 首轮执行后，对 `failed` 漏洞按
   `orchestration.verify_max_retries` 再向模型要一次策略；提示词包含上次命令和失败输出，
   要求选择不同的验证脚本。相同命令不会重复执行。

| 配置 | 默认 | 说明 |
|---|---:|---|
| `orchestration.verify_max_retries` | 0 | 0 表示关闭；建议 Agent 演示设为 1 |

验证记录：

| 场景 | 结果 |
|---|---|
| `langgraph` + 正常源码（项目 41） | 5 漏洞（4 verified + 1 skipped），`retry_rounds=0` |
| `langgraph` + 空源码（项目 42） | 0 漏洞，验证阶段 `success` 并备注跳过，报告生成 |
| `langgraph` + 验证脚本全部失败（项目 43） | 4 failed，`retry_rounds=1`，重规划日志出现，项目仍 `completed` |
| `fixed` + 正常源码（项目 44） | 5 漏洞（4 verified + 1 skipped），`retry_rounds=0` |

## LLM 模式与降级

配置 `llm.base_url`、`llm.model`、`llm.api_key` 后，运行时按角色调用模型：

| 角色 | LLM 用途 |
| --- | --- |
| `general` | 生成分析计划 JSON |
| `code_analyst` | 基于源码片段输出漏洞候选 JSON 数组（必须通过文件/行号/证据落地校验） |
| `vuln_verifier` | 为待验证漏洞选择验证策略，只允许引用 `/src/verify/` 下已有脚本 |
| `report_writer` | 生成攻击路径与修复建议 |
| `env_checker` / `ops_assistant` | 确定性工具角色，不调用 LLM |

降级规则：

- 未配置 LLM：启动时写“规则引擎模式”日志和 `system` 聊天消息。
- 调用失败（超时/401/403/429/5xx）按 `llm.max_retries` 重试；仍失败则本轮剩余阶段切换规则引擎，并写 `warn` 日志和 `system` 消息。
- LLM 输出 JSON/Schema 校验失败同样触发降级。
- LLM 生成漏洞时，`file_path` 必须属于已扫描文件，证据必须能在源码中定位；`verify_code_text` 只接受 `/src/verify/` 下的 Python 脚本。
- token 用量累计写入 `resource_usages.token_count`；规则引擎模式恒为 0。

已用本地 OpenAI 兼容 mock 服务验证两条链路：LLM 模式完整产出 5 条漏洞/1 条 LLM 攻击路径；指向失败地址时自动降级，仍完成 5 条漏洞评估。

## 目录结构

```text
auto/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI 入口、生命周期、异常包络
│   │   ├── api/                  # auth/projects/results/monitor/config/ws
│   │   ├── core/                 # 配置、数据库、安全、错误码、日志脱敏
│   │   ├── models/               # SQLAlchemy 模型（13 张表）
│   │   ├── schemas/              # Pydantic 请求模型
│   │   ├── services/             # 项目、结果、报告、监控、配置、维护
│   │   ├── orchestration/        # 运行状态视图（RunState）
│   │   ├── scheduler/            # 阶段调度与取消
│   │   ├── workers/              # 6 类角色
│   │   ├── tools/                # 工具注册表与沙箱工具执行层
│   │   ├── rule_engine/          # 5 类检测规则
│   │   ├── sandbox/              # Docker/SSH、源码同步
│   │   └── ws/                   # 连接管理
│   └── tests/
├── frontend/src/
│   ├── api/                      # axios 客户端与接口封装
│   ├── charts/                   # ECharts 资源折线图
│   ├── components/               # 布局、状态标签
│   ├── hooks/                    # WebSocket 订阅
│   ├── pages/                    # 9 个页面
│   ├── router/                   # 路由与守卫
│   └── store/                    # Zustand 登录态
├── db/init.sql                   # DDL、索引、默认配置、演示用户
├── examples/vuln-demo/           # 5 类漏洞的示例项目
├── sandbox/                      # Dockerfile + helper.py
├── scripts/                      # 初始化、镜像构建、源码同步
├── docs/api.md                   # 接口说明
├── docker-compose.yml            # VM 上的 PostgreSQL 16
├── .env.example
└── 项目需求.md
```

## 环境依赖

- Windows 10/11（应用与前端）
- Python 3.11+
- Node.js 20+
- 一台预置 Linux VM：
  - Docker Engine 24+ 与 OpenSSH Server
  - 4 vCPU / 8 GB 内存 / 80 GB 磁盘（建议）
  - 专用 `eval` 用户，加入 `docker` 组，仅允许 SSH 密钥登录

## 快速开始

### 1. 准备 Linux VM

在 VM 上（Ubuntu 示例）：

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-v2 openssh-server
sudo systemctl enable --now docker ssh

sudo useradd -m -s /bin/bash eval
sudo usermod -aG docker eval
```

在 Windows 上生成密钥并上传公钥：

```powershell
ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\ase_eval_key
type $env:USERPROFILE\.ssh\ase_eval_key.pub | ssh eval@<VM_IP> "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

在 `%USERPROFILE%\.ssh\config` 中登记 IdentityFile（Docker SDK 使用系统 OpenSSH）：

```text
Host <VM_IP>
  HostName <VM_IP>
  User eval
  IdentityFile C:/Users/<you>/.ssh/ase_eval_key
  IdentitiesOnly yes
```

验证：

```bash
ssh eval@<VM_IP> docker info
```

### 2. 构建沙箱镜像

把仓库同步/克隆到 VM，在仓库根目录执行：

```bash
bash scripts/build_sandbox_image.sh
# 等价于：docker build -f sandbox/Dockerfile -t ase-sandbox:1.0 .
```

### 3. 启动 PostgreSQL

`docker-compose-v2.yml` 从环境变量读取连接信息，**不再内置真实密码**。在 VM 的仓库根目录创建 `.env`（可复制 `.env.example`），至少设置 `DB_PASSWORD` 和 `DB_BIND_ADDR`：

```bash
cp .env.example .env
# 编辑 .env 后再启动
docker compose -f docker-compose-v2.yml up -d
# 若文件已改名为 docker-compose.yml，直接 docker compose up -d
```

`.env` 至少包含：

```dotenv
DB_USER=postgres
DB_PASSWORD=<强密码>
DB_NAME=sec_eval
DB_PORT=5433
DB_BIND_ADDR=<VM 的 host-only/内网 IP>
```

> 不要把真实密码提交到仓库。`DB_BIND_ADDR` 应使用 host-only/内网地址并由防火墙限制来源；Windows 后端 `.env` 的 `DB_PASSWORD` 必须与数据库实际密码一致。

首次创建数据卷时会自动执行 `db/init.sql`。若数据卷已存在，手动执行：

```bash
docker exec -i ase-postgres psql -U postgres -d sec_eval < db/init.sql
```

从 Windows 验证连通性：

```bash
psql "postgresql://postgres:<密码>@<VM_IP>:5433/sec_eval" -c "select 1"
```

> `5433` 只应绑定 host-only/内网地址，云主机请用安全组或 SSH 隧道限制来源 IP。

### 4. 启动后端

```bash
cd backend
uv venv .venv --python 3.11
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
```

在仓库根目录复制 `.env.example` 为 `.env`，填写 `DB_*`、`JWT_SECRET`、`DOCKER_HOST`、`DOCKER_SSH_KEY`、`VM_WORKSPACE_DIR`：

- `JWT_SECRET` 必须 ≥ 32 字符，否则后端拒绝启动。
- `DOCKER_HOST=ssh://eval@<VM_IP>`。
- `DOCKER_SSH_KEY` 用于源码同步（paramiko）；Docker SDK 的 SSH 连接使用上面的 `~/.ssh/config`。

启动（在**仓库根目录**执行，默认读取 `.env` 的 `APP_HOST` / `APP_PORT`）：

```bash
backend/.venv/Scripts/python.exe scripts/run_backend.py --reload
```

等价于直接调用 uvicorn（需要先 `cd backend`）：

```bash
cd backend
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

- OpenAPI：`http://127.0.0.1:<APP_PORT>/docs`（当前 `.env` 为 `8001`）
- 健康检查：`http://127.0.0.1:<APP_PORT>/healthz`

> 端口以 `.env` 的 `APP_PORT` 为准；`run_backend.py` 会用它，避免终端命令与前端代理配置不一致。

### 5. 启动前端

```bash
cd frontend
npm install
npm run dev
```

访问 <http://127.0.0.1:5173>。Vite 将 `/api`（含 WebSocket）代理到仓库根 `.env` 中 `ASE_API_TARGET` 指定的地址，默认 `http://127.0.0.1:8000`；本机 8000 被占用时改为 `http://127.0.0.1:8001`。

### 6. 初始化管理员

```bash
backend/.venv/Scripts/python.exe scripts/init_system.py --username admin --password "Admin@12345"
```

也可以在登录页的“系统初始化”面板中创建。之后系统预置演示账号：

```text
demo / demo12345
```

### 7. 运行演示

1. 使用 `admin` 登录（或 `demo` 体验普通用户视角）。
2. 新建项目：
   - 项目名称：`vuln-demo 安全评估`
   - 源码路径：`D:\pythoncode\auto\examples\vuln-demo`（绝对路径）
   - 任务说明：`重点检查 SQL 注入、命令注入、文件操作与越权。`
   - 隔离环境：Docker 容器
3. 进入详情页点击“启动任务”。
4. 打开监控页，观察阶段、6 类角色、日志、聊天消息、资源折线图。
5. 查看漏洞列表（5 条：4 条 `verified` + 1 条 `skipped`）、攻击路径（≥1 条）与报告（可预览/下载 HTML）。
6. 停止任务、删除项目，确认容器、VM 工作区与数据库子资源被清理。

> 未配置 LLM 时直接使用规则引擎；配置后使用 LLM 模式。若模型调用失败，本轮剩余阶段会自动切换规则引擎，并在监控页的系统消息中提示。

## 测试与检查

```bash
# 后端单测（规则引擎、LLM 输出解析、执行能力、密码/JWT、配置校验）
cd backend && .venv/Scripts/python.exe -m pytest

# 前端类型检查与生产构建
cd frontend && npm run build
```

验证情况：

- 后端 19 个单测通过（规则引擎、LLM 输出解析、执行能力、密码/JWT、配置校验）。
- 嵌入式 PostgreSQL 16 完成 52 项集成冒烟：`init.sql`、初始化/登录、项目 CRUD、配置校验、启动失败路径、停止语义、结果/报告/下载、WS 快照与 4401、级联删除。
- 在真实 Linux VM 上跑通 `vuln-demo`：源码同步 → Docker 沙箱 → 规则引擎 → 4 条验证通过 + 1 条跳过 → 1 条攻击路径 → 报告生成/下载，项目 `completed`。
- AC-09 沙箱约束已实测：`NetworkMode=none`、`cap-drop ALL`、非 root、只读 `/src`、可写 `/workspace`、无外网。
- 本地 OpenAI 兼容 mock 服务验证了 LLM 模式与失败降级各一次完整运行。

手动同步源码（排查同步问题）：

```bash
backend/.venv/Scripts/python.exe scripts/sync_source.py examples/vuln-demo --project-id 1 --run-no 1
```

## 安全设计要点

- 沙箱默认 `--network none`；仅 `sandbox.network_enabled=true` 时切到 `bridge`。
- `--cap-drop ALL`、`no-new-privileges`、`--pids-limit`、CPU/内存限额、非 root（1000:1000）。
- 源码在 VM 上以 `:ro` 挂载到 `/src`；可写目录仅为 `/workspace`。
- 命令以 argv 数组执行，禁止 shell 拼接；只允许白名单可执行文件；单条命令超时与输出截断。
- 源码同步前后计算 SHA-256 指纹，不一致则本轮失败。
- 密码只存 bcrypt 哈希；JWT 与 API Key 不进入日志/响应；配置读取时 API Key 脱敏。
- 报告 HTML 全部动态内容转义，自包含、无外部资源；前端使用 sandbox iframe 渲染。
- 删除、停止等破坏性操作需要确认；运行中项目禁止删除。

## 常见问题

**VM 上报 `required variable DB_PASSWORD is missing a value`**  
说明没有设置 `DB_PASSWORD`。在 compose 文件同目录的 `.env` 中设置 `DB_PASSWORD=<强密码>`，或使用 `--env-file` 指定；不要把真实密码写回 compose 文件。

**修改 `.env` 密码后仍然连不上数据库**  
PostgreSQL 只在数据卷首次初始化时使用 `POSTGRES_PASSWORD`。若 `ase_pgdata` 已存在，改 `.env` 不会修改已有密码。演示环境可清空卷重建（会丢数据）：

```bash
docker compose -f docker-compose-v2.yml down -v
docker compose -f docker-compose-v2.yml up -d
```

**后端启动报 `JWT_SECRET 缺失或长度小于 32`**  
在仓库根目录 `.env` 中配置至少 32 字符的 `JWT_SECRET`。

**Docker 连接失败 / `ssh: identity file not accessible`**  
确认 `DOCKER_HOST=ssh://eval@<VM_IP>`、`eval` 已加入 `docker` 组，且 `~/.ssh/config` 指向正确私钥；先在命令行执行 `ssh eval@<VM_IP> docker info` 验证。

**源码同步失败**  
检查 VM 磁盘空间、`VM_WORKSPACE_DIR` 写权限、`DOCKER_SSH_KEY` 路径与私钥格式；同步脚本会输出本地/远端指纹，指纹不一致通常意味着传输或解压异常。

**VM 上 `docker pull/build` 卡在拉取镜像**  
检查 Docker daemon 代理配置（需要 root）：

```bash
sudo cat /etc/systemd/system/docker.service.d/http-proxy.conf
```

若仍指向失效的 `127.0.0.1:7897`，改为 Windows 主机在 VMware NAT 中的地址（例如 `<host-ip>:7897`），或删除代理配置后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl restart docker
```

**启动返回 `PROJECT_CONCURRENCY_LIMIT`**  
默认最多同时运行 2 个项目；在系统配置页调整并发数，或停止其他运行中的项目。

**前端 WebSocket 一直“重连中”**  
确认后端已启动且 Vite 代理包含 `ws: true`；检查浏览器 Network 中 `/api/projects/{id}/stream` 的关闭码（4401/4403/4404）。

**报告接口返回 `REPORT_NOT_READY`**  
任务尚未执行到 `report_generate` 或报告生成失败；查看监控页日志与阶段状态。

## 文档

- 需求基线：[`项目需求.md`](项目需求.md)
- 接口说明：[`docs/api.md`](docs/api.md)
- 验收结果：[`docs/acceptance-results.md`](docs/acceptance-results.md)
- OpenAPI：后端启动后访问 `/docs`
