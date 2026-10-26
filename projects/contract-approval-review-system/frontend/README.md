# 前端控制台

零构建的原生 HTML/CSS/JS 页面，直接调用后端现有接口。

## 启动

先启动后端：

```bash
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

然后访问：

```text
http://127.0.0.1:8000/ui/
```

页面由 FastAPI 直接挂载（`app/main.py` 中的 `/ui`），与 API 同源，推荐这种方式。
也支持用 `file://` 或本地静态服务器打开：前端会自动指向 `http://127.0.0.1:8000`，
后端已开放本地开发 CORS；也可用 `?api=http://127.0.0.1:8001` 指定其他后端。

## 已接入的功能

| 功能 | 使用的接口 |
|---|---|
| 拉取待办并去重 | `POST /api/tools/list_pending_contract_approvals` |
| 任务列表 / 状态刷新 | `GET /api/tasks` |
| 审批详情聚合 | `GET /api/tools/get_contract_approval/{instance_id}` |
| 附件下载与 SHA-256 校验 | `POST /api/tools/download_contract_attachment` |
| 合同原文/字段/条款/命中 | `GET /api/tasks/{task_id}/content` |
| 文档解析 | `POST /api/tools/parse_contract_document` |
| 规则审查 | `POST /api/tools/run_contract_rules` |
| 保存审查结果 | `POST /api/tools/save_review_result` |
| 幂等回写评论 | `POST /api/tools/write_approval_comment` |
| 一键审查 / 重试 | `POST /api/tasks/{id}/full-review`、`/retry` |
| 任务状态轮询 | `GET /api/tasks/{task_id}/status` |
| Mock 故障注入 | `POST /mock-upstream/admin/faults` |
| 恢复缺失附件 | `POST /mock-upstream/admin/attachments/{id}/restore` |
| 重置 Mock 上游 | `POST /mock-upstream/admin/reset` |

任务表的「一键审查」会入队异步流水线，页面每 1.5 秒轮询，`done`/`blocked` 后停止；
阻塞任务显示「重试」按钮。

## 使用流程

1. 点击「拉取待办」，生成 4 个任务。
2. 直接点「一键审查」即可跑完整闭环；也可以点「查看详情」逐步操作。
3. `APV-2026-001` 会得到高风险；`APV-2026-003` 会展示 OCR + partial + 低风险。
4. `APV-2026-004` 会因附件缺失进入 `blocked`，在 Mock 面板恢复附件 5 后点「重试」。
5. 点「查看原文」可查看解析全文、8 个基本信息、8 类条款和规则命中位置。
6. 详情页的「解析」「规则审查」可单独调用工具；也可在表单中保存结果并「回写评论」。
6. 在 Mock 面板打开 `comment` 故障后回写，可观察任务进入 `blocked + failed`；关闭故障再重试即可恢复 `done`。

## 文件

- `index.html`：页面结构与操作区。
- `style.css`：简单扁平样式。
- `app.js`：接口调用、渲染、轮询与事件绑定。
