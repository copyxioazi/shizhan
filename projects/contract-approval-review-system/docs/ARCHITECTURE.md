# 架构说明

完整设计见：

- `.claude/skills/contract-approval-review-system/SKILL.md`
- `.claude/skills/contract-approval-review-system/references/architecture.md`

## 模块职责

| 模块 | 职责 | 当前状态 |
|---|---|---|
| `app/main.py` | FastAPI 入口、路由注册、异常响应、lifespan | 框架完成 |
| `app/config.py` | 环境变量与路径 | 框架完成 |
| `app/db.py` | SQLite 短连接、WAL、脚本执行 | 框架完成 |
| `app/api/tools.py` | 7 个工具 REST 包装 | 已完成 |
| `app/api/tasks.py` | 一键审查、重试、状态、任务列表 | 已完成 |
| `app/api/admin.py` | 规则 CRUD | 已完成 |
| `app/web/routes.py` | 5 个业务页面 + 管理台 | 占位页；日常使用 `/ui` |
| `app/services/tool_functions.py` | 7 个同步工具 | 已完成 |
| `app/services/upstream_client.py` | Mock 上游适配层 | 已完成 |
| `app/services/approvals.py` | 拉取、去重、详情聚合 | 已完成 |
| `app/services/attachments.py` | 下载、校验、安全存储、主附件选择 | 已完成 |
| `app/services/review.py` | 结果生成与持久化 | 已完成 |
| `app/services/llm.py` | 可选润色与模板回退 | 已完成（默认关闭） |
| `app/services/comments.py` | 幂等回写与评论日志 | 已完成 |
| `app/services/parser/*` | PDF/DOCX/OCR、字段、条款、位置 | 已完成 |
| `app/services/rules/*` | 6 种匹配模式、汇总、关注点 | 已完成 |
| `app/services/pipeline.py` | 可恢复流水线 | 已完成 |
| `app/services/queue.py` | asyncio 队列 + 2 worker | 已完成 |
| `app/services/tasks.py` | 入队、重试、启动恢复 | 已完成 |
| `app/mock_upstream/*` | Mock 审批系统 | 已完成 |
| `frontend/*` | 零构建 Web 控制台 `/ui` | 已完成 |
| `scripts/init_db.py` | 双库初始化、样例、种子 | 可用 |
| `scripts/generate_samples.py` | 示例合同生成 | 已完成（确定性） |
| `scripts/demo_closed_loop.py` | 闭环演示 | 已完成 |

## 关键约束

- 7 个工具同步；只有一键审查异步。
- 状态：`pending/parsing/reviewing/blocked/done`；不新增 `queued`，用 `stage=queued`。
- 回写：`not_written → writing → success|failed`；失败同时任务 `blocked`。
- 规则全数据驱动，6 种 `match_mode`。
- 主附件审查，其余附件只入库。
- SQLite 双库物理隔离：`data/app.db`、`data/mock_upstream.db`。
- 启动时中间态转 `blocked`。
