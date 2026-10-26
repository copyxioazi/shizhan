# 合同审批审查系统

当前阶段：**核心闭环已打通**（拉取去重 → 下载校验 → PDF/DOCX/OCR 解析 → 规则审查
→ 结果保存 → 幂等回写 → 阻塞重试），并提供可用的 Web 控制台。

- 需求来源：`合同审批审查系统.md`
- 实现指南：`.claude/skills/contract-approval-review-system/SKILL.md`

## 快速开始

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -U pip -i https://pypi.org/simple
.venv/Scripts/python.exe -m pip install -r requirements.txt -i https://pypi.org/simple
.venv/Scripts/python.exe scripts/init_db.py
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- 前端控制台：<http://127.0.0.1:8000/ui/>
- 服务端渲染页面：<http://127.0.0.1:8000/web/pending>
- 健康检查：<http://127.0.0.1:8000/health>
- API 文档：<http://127.0.0.1:8000/docs>

配置：可复制 `.env.example` 为 `.env`，应用与 Docker Compose 都会自动读取。

## Docker 部署

项目使用文件型 SQLite，不需要单独的数据库容器；数据通过 `./data` 卷持久化。

```bash
cp docker.env.example docker.env     # 填写数据库目录/路径和端口
docker compose --env-file docker.env up -d --build
docker compose logs -f contract-review
```

- 前端：`http://<虚拟机IP>:8000/ui/`
- 换端口：`APP_PORT=8080 docker compose up -d`
- 换数据目录：`DATA_DIR=/srv/contract-review-data docker compose up -d`
- 重置数据：`docker compose exec contract-review python scripts/init_db.py --reset`

完整说明见 [`docs/DOCKER.md`](docs/DOCKER.md)。

## 前端控制台

`frontend/` 是零构建的原生 HTML/CSS/JS 页面，由 FastAPI 直接托管在 `/ui`，
**不需要单独启动前端服务或安装 Node 依赖**。

```bash
# 先启动后端（同时托管前端）
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

然后打开 <http://127.0.0.1:8000/ui/>。功能包括：拉取待办、任务列表、审批详情、
附件下载、保存审查结果、幂等回写，以及 Mock 故障注入/附件恢复/重置。
详见 [`frontend/README.md`](frontend/README.md)。

## 测试与闭环演示

```bash
# 单元 + 集成 + E2E（32 个用例）
.venv/Scripts/python.exe -m pytest -q

# 完整闭环：去重拉取、四类合同审查、OCR、阻塞恢复、幂等回写
.venv/Scripts/python.exe scripts/demo_closed_loop.py
```

演示脚本会重置演示数据；若 8000 端口没有服务，会自动拉起一个 uvicorn 进程，
结束后自动关闭。已手动启动服务时可加 `--no-reset` 复用当前数据。

> 如果本机 pip 镜像不可用，安装时显式使用 `-i https://pypi.org/simple`。

## 当前进度

- FastAPI 应用入口、路由分层、统一异常响应。
- SQLite 双库 schema：本地库 8 张表，Mock 库 4 张表。
- 7 个同步工具函数全部实现，包含解析与规则审查。
- Mock 上游：4 个审批单、5 个附件、评论幂等、附件恢复、故障注入。
- 待办拉取与 `approval_code` 去重、审批详情聚合。
- 附件下载、SHA-256 校验、安全落盘、主附件选择。
- PDF（pdfplumber）/ DOCX（python-docx）/ 扫描件（RapidOCR）解析；
  8 个基本信息 + 8 类条款，带原文、结构化位置与 `found/missing/invalid`。
- 6 种 `match_mode` 规则引擎、14 条种子规则、命中证据、风险汇总与关注点。
- 异步流水线（2 worker）、一键审查、分阶段重试、启动恢复、状态轮询。
- 审查结果 upsert 与幂等评论回写（含失败重试）。
- 管理端规则 CRUD（JSON API）。
- 合同原文查看：全文、8 个基本信息、8 类条款、命中证据与位置。
- 确定性示例合同生成（PDF / DOCX / 扫描 PNG）。
- 零构建前端控制台 `/ui`，支持一键审查、重试与原文查看。

## 尚未实现

- `/web/*` 服务端渲染页面仍为占位；日常演示请使用 `/ui`。
- 生产级认证、权限与部署加固。
- LLM 润色默认关闭；开启后可回退模板。

## 目录

```text
app/
├─ main.py                 # 应用入口
├─ config.py               # 环境变量与路径
├─ db.py                   # sqlite3 连接
├─ schema.sql              # 本地库 DDL
├─ status.py               # 状态/阶段/错误码
├─ errors.py               # 统一异常
├─ api/                    # 工具、任务、管理端 REST
├─ web/                    # 服务端渲染页面
├─ services/               # 领域服务（当前为接口骨架）
│  ├─ parser/              # PDF/DOCX/OCR
│  └─ rules/               # 规则引擎
├─ mock_upstream/          # 同进程 Mock 审批系统
├─ seed/rules.json         # 14 条种子规则
├─ templates/              # Jinja2 页面
└─ static/                 # CSS/JS
scripts/                   # 初始化、样例、演示
sample_contracts/          # 示例合同目录
data/                      # 运行时 SQLite 与附件
docs/                      # 工具、架构、演示文档
tests/                     # pytest
```

## 实现顺序

见 `.claude/skills/contract-approval-review-system/SKILL.md` 的“实施顺序”一节。
