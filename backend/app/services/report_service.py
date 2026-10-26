"""报告生成：六个固定章节，Markdown + 自包含 HTML。"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.timeutil import cn_time, now_utc
from app.models import (
    AttackPath,
    AttackPathItem,
    IsolationEnv,
    Project,
    Report,
    RuntimeStage,
    Vulnerability,
    WorkerTask,
)

RISK_LABELS = {
    "critical": "严重",
    "high": "高危",
    "medium": "中危",
    "low": "低危",
    "info": "提示",
}
RISK_ORDER = ["critical", "high", "medium", "low", "info"]
STAGE_LABELS = {
    "environment_scan": "环境检查",
    "code_analysis": "代码分析",
    "vulnerability_verify": "漏洞验证",
    "report_generate": "报告生成",
}
REMEDIATION = {
    "critical": "立即修复：对涉及外部输入的命令、SQL 与文件路径做白名单校验，移除动态执行。",
    "high": "尽快修复：使用参数化查询、路径规范化与最小权限，禁止拼接不可信输入。",
    "medium": "计划修复：补充归属校验与访问控制，移除硬编码凭据并改由环境变量注入。",
    "low": "在下一迭代修复，并补充自动化测试防止回归。",
    "info": "持续关注，按安全编码规范整改。",
}


def _md_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _duration(start: datetime | None, end: datetime | None) -> str:
    if not start or not end:
        return "-"
    seconds = max(0, int((end - start).total_seconds()))
    return f"{seconds // 60}分{seconds % 60}秒"


def _build_markdown(
    project: Project,
    env: IsolationEnv | None,
    stages: list[RuntimeStage],
    workers: list[WorkerTask],
    vulnerabilities: list[Vulnerability],
    paths: list[tuple[AttackPath, list[tuple[AttackPathItem, Vulnerability]]]],
    image: str,
    remediation: list[str] | None = None,
) -> tuple[str, str]:
    risk_counts = {level: 0 for level in RISK_ORDER}
    for vuln in vulnerabilities:
        risk_counts[vuln.risk_level] = risk_counts.get(vuln.risk_level, 0) + 1
    highest = next((level for level in RISK_ORDER if risk_counts.get(level)), None)

    started = min((s.started_at for s in stages if s.started_at), default=None)
    finished = max((s.finished_at for s in stages if s.finished_at), default=None)

    lines: list[str] = []
    lines.append(f"# {project.project_name} 安全评估报告")
    lines.append("")
    lines.append("## 1. 项目概述")
    lines.append("")
    lines.append(f"- 项目名称：{project.project_name}")
    lines.append(f"- 源码来源：{project.source_type} `{project.source_path}`")
    lines.append(f"- 任务说明：{project.task_content}")
    lines.append(f"- 运行轮次：第 {stages[0].run_no if stages else '-'} 轮")
    lines.append(f"- 开始时间：{cn_time(started) or '-'}")
    lines.append(f"- 结束时间：{cn_time(finished) or '-'}")
    env_text = "Docker 容器" if env and env.env_type == "docker" else "本机目录（P2）"
    lines.append(f"- 隔离环境：{env_text}")
    if env and env.env_type == "docker":
        lines.append(f"- 容器名：`{env.env_ref or '-'}`，镜像：`{image}`")
    lines.append("")

    lines.append("## 2. 执行过程")
    lines.append("")
    lines.append("| 阶段 | 状态 | 开始时间 | 结束时间 | 耗时 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for stage in stages:
        lines.append(
            "| {name} | {status} | {start} | {end} | {duration} |".format(
                name=STAGE_LABELS.get(stage.stage_name, stage.stage_name),
                status=stage.stage_status,
                start=cn_time(stage.started_at) or "-",
                end=cn_time(stage.finished_at) or "-",
                duration=_duration(stage.started_at, stage.finished_at),
            )
        )
    lines.append("")
    if workers:
        lines.append("角色任务：")
        lines.append("")
        lines.append("| 角色 | 状态 | 结果摘要 |")
        lines.append("| --- | --- | --- |")
        for worker in workers:
            summary = (worker.result_summary or worker.error_message or "-")[:200]
            lines.append(
                f"| {worker.worker_role} | {worker.task_status} | {_md_cell(summary)} |"
            )
        lines.append("")

    lines.append("## 3. 漏洞汇总")
    lines.append("")
    lines.append(
        "按风险等级统计："
        + "，".join(
            f"{RISK_LABELS[level]} {risk_counts[level]} 个" for level in RISK_ORDER
        )
    )
    lines.append("")
    if vulnerabilities:
        lines.append("| 编号 | 标题 | 风险 | 文件 | 验证状态 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for vuln in vulnerabilities:
            lines.append(
                "| {code} | {title} | {risk} | `{file}` | {verify} |".format(
                    code=vuln.vuln_code,
                    title=_md_cell(vuln.vuln_title),
                    risk=RISK_LABELS.get(vuln.risk_level, vuln.risk_level),
                    file=_md_cell(vuln.file_path),
                    verify=vuln.verify_status,
                )
            )
    else:
        lines.append("本轮未发现漏洞。")
    lines.append("")

    lines.append("## 4. 攻击路径")
    lines.append("")
    if paths:
        for path, items in paths:
            lines.append(f"### {path.path_code} {path.path_title}")
            lines.append("")
            lines.append(path.path_summary)
            lines.append("")
            for item, vuln in items:
                lines.append(
                    f"{item.step_order}. {item.step_text}（{vuln.vuln_code} {vuln.vuln_title}，"
                    f"{RISK_LABELS.get(vuln.risk_level, vuln.risk_level)}）"
                )
            lines.append("")
            lines.append(f"最终影响：{path.final_impact_text}")
            lines.append("")
    else:
        lines.append("本轮未生成攻击路径。")
        lines.append("")

    lines.append("## 5. 风险结论")
    lines.append("")
    if highest:
        lines.append(
            f"总体风险等级：**{RISK_LABELS[highest]}**。"
            f"共发现 {len(vulnerabilities)} 个漏洞，其中最高风险为 {RISK_LABELS[highest]}，"
            f"已验证 {sum(1 for v in vulnerabilities if v.verify_status == 'verified')} 个。"
        )
    else:
        lines.append("总体风险等级：暂未发现可确认漏洞。本轮结果不构成安全保证，建议结合人工复核。")
    lines.append("")

    lines.append("## 6. 修复建议")
    lines.append("")
    if remediation:
        for advice in remediation:
            lines.append(f"- {advice}")
    elif highest:
        for level in RISK_ORDER:
            if risk_counts.get(level):
                lines.append(f"- **{RISK_LABELS[level]}**：{REMEDIATION[level]}")
    else:
        lines.append("- 保持依赖更新、最小权限与日志审计，定期执行安全评估。")
    lines.append("")

    markdown = "\n".join(lines)

    # HTML：所有动态内容转义，CSS 内联，无外部资源
    body: list[str] = []
    body.append(f"<h1>{html.escape(project.project_name)} 安全评估报告</h1>")
    body.append("<h2>1. 项目概述</h2><ul>")
    body.append(f"<li>项目名称：{html.escape(project.project_name)}</li>")
    body.append(
        f"<li>源码来源：{html.escape(project.source_type)} "
        f"<code>{html.escape(project.source_path)}</code></li>"
    )
    body.append(f"<li>任务说明：{html.escape(project.task_content)}</li>")
    body.append(f"<li>运行轮次：第 {stages[0].run_no if stages else '-'} 轮</li>")
    body.append(f"<li>开始时间：{html.escape(cn_time(started) or '-')}</li>")
    body.append(f"<li>结束时间：{html.escape(cn_time(finished) or '-')}</li>")
    body.append(f"<li>隔离环境：{html.escape(env_text)}</li>")
    if env and env.env_type == "docker":
        body.append(
            f"<li>容器名：<code>{html.escape(env.env_ref or '-')}</code>，"
            f"镜像：<code>{html.escape(image)}</code></li>"
        )
    body.append("</ul>")

    body.append("<h2>2. 执行过程</h2>")
    body.append("<table><thead><tr><th>阶段</th><th>状态</th><th>开始</th><th>结束</th><th>耗时</th></tr></thead><tbody>")
    for stage in stages:
        body.append(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                html.escape(STAGE_LABELS.get(stage.stage_name, stage.stage_name)),
                html.escape(stage.stage_status),
                html.escape(cn_time(stage.started_at) or "-"),
                html.escape(cn_time(stage.finished_at) or "-"),
                html.escape(_duration(stage.started_at, stage.finished_at)),
            )
        )
    body.append("</tbody></table>")
    if workers:
        body.append("<table><thead><tr><th>角色</th><th>状态</th><th>结果摘要</th></tr></thead><tbody>")
        for worker in workers:
            summary = (worker.result_summary or worker.error_message or "-")[:200]
            body.append(
                "<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                    html.escape(worker.worker_role),
                    html.escape(worker.task_status),
                    html.escape(summary),
                )
            )
        body.append("</tbody></table>")

    body.append("<h2>3. 漏洞汇总</h2>")
    body.append(
        "<p>"
        + html.escape(
            "，".join(f"{RISK_LABELS[level]} {risk_counts[level]} 个" for level in RISK_ORDER)
        )
        + "</p>"
    )
    if vulnerabilities:
        body.append(
            "<table><thead><tr><th>编号</th><th>标题</th><th>风险</th><th>文件</th><th>验证状态</th></tr></thead><tbody>"
        )
        for vuln in vulnerabilities:
            body.append(
                "<tr><td>{}</td><td>{}</td><td>{}</td><td><code>{}</code></td><td>{}</td></tr>".format(
                    html.escape(vuln.vuln_code),
                    html.escape(vuln.vuln_title),
                    html.escape(RISK_LABELS.get(vuln.risk_level, vuln.risk_level)),
                    html.escape(vuln.file_path),
                    html.escape(vuln.verify_status),
                )
            )
        body.append("</tbody></table>")
    else:
        body.append("<p>本轮未发现漏洞。</p>")

    body.append("<h2>4. 攻击路径</h2>")
    if paths:
        for path, items in paths:
            body.append(
                f"<h3>{html.escape(path.path_code)} {html.escape(path.path_title)}</h3>"
            )
            body.append(f"<p>{html.escape(path.path_summary)}</p><ol>")
            for item, vuln in items:
                body.append(
                    f"<li>{html.escape(item.step_text)}（{html.escape(vuln.vuln_code)} "
                    f"{html.escape(vuln.vuln_title)}）</li>"
                )
            body.append("</ol>")
            body.append(f"<p>最终影响：{html.escape(path.final_impact_text)}</p>")
    else:
        body.append("<p>本轮未生成攻击路径。</p>")

    body.append("<h2>5. 风险结论</h2>")
    if highest:
        body.append(
            f"<p>总体风险等级：<strong>{html.escape(RISK_LABELS[highest])}</strong>。"
            f"共发现 {len(vulnerabilities)} 个漏洞，其中最早列为最高风险的是"
            f"{html.escape(RISK_LABELS[highest])}。</p>"
        )
    else:
        body.append("<p>总体风险等级：暂未发现可确认漏洞。</p>")

    body.append("<h2>6. 修复建议</h2><ul>")
    if remediation:
        for advice in remediation:
            body.append(f"<li>{html.escape(advice)}</li>")
    elif highest:
        for level in RISK_ORDER:
            if risk_counts.get(level):
                body.append(
                    f"<li><strong>{html.escape(RISK_LABELS[level])}</strong>："
                    f"{html.escape(REMEDIATION[level])}</li>"
                )
    else:
        body.append("<li>保持依赖更新、最小权限与日志审计，定期执行安全评估。</li>")
    body.append("</ul>")

    html_doc = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
         max-width: 1100px; margin: 40px auto; padding: 0 24px; color: #1f2329;
         line-height: 1.7; background: #fff; }}
  h1 {{ border-bottom: 2px solid #1677ff; padding-bottom: 12px; }}
  h2 {{ margin-top: 36px; border-left: 4px solid #1677ff; padding-left: 10px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 14px; }}
  th, td {{ border: 1px solid #d9d9d9; padding: 8px 10px; text-align: left; vertical-align: top; }}
  th {{ background: #f5f7fa; }}
  code {{ background: #f5f5f5; padding: 1px 5px; border-radius: 4px; }}
  .meta {{ color: #8c8c8c; font-size: 13px; }}
</style>
</head>
<body>
{body}
<p class="meta">由自动化安全评估系统生成</p>
</body>
</html>
""".format(title=html.escape(f"{project.project_name} 安全评估报告"), body="\n".join(body))
    return markdown, html_doc


async def generate_report(
    project_id: int,
    run_no: int,
    image: str,
    remediation: list[str] | None = None,
) -> Report:
    async with SessionLocal() as db:
        project = await db.get(Project, project_id)
        if project is None:
            raise RuntimeError(f"project {project_id} not found")
        env = await db.scalar(
            select(IsolationEnv).where(IsolationEnv.project_id == project_id)
        )
        stages = (
            (
                await db.execute(
                    select(RuntimeStage)
                    .where(
                        RuntimeStage.project_id == project_id,
                        RuntimeStage.run_no == run_no,
                    )
                    .order_by(RuntimeStage.id)
                )
            )
            .scalars()
            .all()
        )
        workers = (
            (
                await db.execute(
                    select(WorkerTask)
                    .join(RuntimeStage, RuntimeStage.id == WorkerTask.stage_id)
                    .where(
                        RuntimeStage.project_id == project_id,
                        RuntimeStage.run_no == run_no,
                    )
                    .order_by(WorkerTask.id)
                )
            )
            .scalars()
            .all()
        )
        vulnerabilities = (
            (
                await db.execute(
                    select(Vulnerability)
                    .where(
                        Vulnerability.project_id == project_id,
                        Vulnerability.run_no == run_no,
                    )
                    .order_by(Vulnerability.vuln_code)
                )
            )
            .scalars()
            .all()
        )
        path_rows = (
            (
                await db.execute(
                    select(AttackPath)
                    .where(
                        AttackPath.project_id == project_id,
                        AttackPath.run_no == run_no,
                    )
                    .order_by(AttackPath.path_code)
                )
            )
            .scalars()
            .all()
        )
        paths: list[tuple[AttackPath, list[tuple[AttackPathItem, Vulnerability]]]] = []
        for path in path_rows:
            item_rows = (
                await db.execute(
                    select(AttackPathItem, Vulnerability)
                    .join(Vulnerability, Vulnerability.id == AttackPathItem.vuln_id)
                    .where(AttackPathItem.path_id == path.id)
                    .order_by(AttackPathItem.step_order)
                )
            ).all()
            paths.append((path, [(item, vuln) for item, vuln in item_rows]))

        markdown, html_doc = _build_markdown(
            project, env, stages, workers, vulnerabilities, paths, image, remediation
        )

        directory = settings.reports_path / str(project_id)
        directory.mkdir(parents=True, exist_ok=True)
        md_file = directory / f"report_{run_no}.md"
        html_file = directory / f"report_{run_no}.html"
        md_file.write_text(markdown, encoding="utf-8")
        html_file.write_text(html_doc, encoding="utf-8")

        relative_path = Path("reports") / str(project_id) / f"report_{run_no}.html"
        report = await db.scalar(
            select(Report).where(
                Report.project_id == project_id, Report.run_no == run_no
            )
        )
        if report is None:
            report = Report(
                project_id=project_id,
                run_no=run_no,
                report_markdown=markdown,
                report_html=html_doc,
                report_file_path=relative_path.as_posix(),
                created_at=now_utc(),
            )
            db.add(report)
        else:
            report.report_markdown = markdown
            report.report_html = html_doc
            report.report_file_path = relative_path.as_posix()
            report.created_at = now_utc()
        await db.commit()
        await db.refresh(report)
        return report
