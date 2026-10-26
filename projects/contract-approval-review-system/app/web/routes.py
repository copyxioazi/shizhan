"""Web 页面路由。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.errors import NotImplementedFeature
from app.web.viewmodels import risk_label, status_label

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory=str(settings.base_dir / "app" / "templates"))


def _render(request: Request, name: str, **context):
    base = {"request": request, "risk_label": risk_label, "status_label": status_label}
    base.update(context)
    return templates.TemplateResponse(request, name, base)


@router.get("/", include_in_schema=False)
def index():
    return RedirectResponse(url="/web/pending")


@router.get("/web/pending", response_class=HTMLResponse)
def pending(request: Request):
    return _render(request, "pending.html", page_title="待办列表")


@router.get("/web/tasks/{task_id}/detail", response_class=HTMLResponse)
def task_detail(request: Request, task_id: int):
    return _render(request, "detail.html", page_title="审批详情", task_id=task_id)


@router.get("/web/tasks/{task_id}/parse", response_class=HTMLResponse)
def task_parse(request: Request, task_id: int):
    return _render(request, "parse.html", page_title="解析结果", task_id=task_id)


@router.get("/web/tasks/{task_id}/hits", response_class=HTMLResponse)
def task_hits(request: Request, task_id: int):
    return _render(request, "hits.html", page_title="规则命中", task_id=task_id)


@router.get("/web/tasks/{task_id}/result", response_class=HTMLResponse)
def task_result(request: Request, task_id: int):
    return _render(request, "result.html", page_title="结果处理", task_id=task_id)


@router.get("/web/admin/rules", response_class=HTMLResponse)
def admin_rules(request: Request):
    return _render(request, "admin/rules.html", page_title="规则管理")


@router.get("/web/admin/rules/new", response_class=HTMLResponse)
def admin_rule_new(request: Request):
    return _render(request, "admin/rule_form.html", page_title="新增规则", rule=None)


@router.get("/web/admin/rules/{rule_id}/edit", response_class=HTMLResponse)
def admin_rule_edit(request: Request, rule_id: int):
    return _render(
        request, "admin/rule_form.html", page_title="编辑规则", rule_id=rule_id, rule=None
    )


@router.get("/web/admin/tasks", response_class=HTMLResponse)
def admin_tasks(request: Request):
    return _render(request, "admin/tasks.html", page_title="任务管理")


@router.get("/web/admin/logs", response_class=HTMLResponse)
def admin_logs(request: Request):
    return _render(request, "admin/logs.html", page_title="日志查看")


@router.get("/web/admin/mock", response_class=HTMLResponse)
def admin_mock(request: Request):
    return _render(request, "admin/mock.html", page_title="Mock 管理")


@router.post("/web/actions/pull")
def pull_action():
    raise NotImplementedFeature("Web 拉取待办动作尚未实现")
