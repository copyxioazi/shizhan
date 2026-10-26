"""单实例进程内调度器。

固定阶段顺序：
environment_scan -> code_analysis -> vulnerability_verify -> report_generate

每个阶段按第 7 章映射串行执行角色；主角色失败 -> 阶段失败 -> 项目失败。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from sqlalchemy import func, select, update

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.errors import ApiError
from app.core.logging import get_logger, sanitize
from app.core.timeutil import cn_time, now_utc
from app.models import (
    IsolationEnv,
    Project,
    Report,
    RuntimeStage,
    Vulnerability,
    WorkerTask,
)
from app.orchestration.orchestrator import (
    LANGGRAPH_AVAILABLE,
    FixedOrchestrator,
    LangGraphOrchestrator,
    RunAborted,
    StageAborted,
    StageHooks,
)
from app.orchestration.state import RunState
from app.sandbox.manager import SandboxManager, SandboxRuntime, SandboxSpec
from app.sandbox.source_sync import cleanup_remote_tmp, sync_source
from app.services.config_service import get_raw_config
from app.services.events import publish
from app.services.llm_runtime import LLMRuntime
from app.tools.executor import ToolExecutor
from app.services.monitor_service import add_chat, add_log, add_resource
from app.workers import WorkerContext, WorkerError, run_worker

logger = get_logger(__name__)

STAGE_ORDER = [
    "environment_scan",
    "code_analysis",
    "vulnerability_verify",
    "report_generate",
]

STAGE_ROLES: dict[str, list[tuple[str, bool]]] = {
    "environment_scan": [("env_checker", True), ("ops_assistant", False)],
    "code_analysis": [("code_analyst", True), ("general", False)],
    "vulnerability_verify": [("vuln_verifier", True), ("code_analyst", False)],
    "report_generate": [("report_writer", True), ("general", False)],
}


class Scheduler:
    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._events: dict[int, asyncio.Event] = {}
        self._samplers: dict[int, asyncio.Task[None]] = {}

    def start(self, project_id: int, run_no: int) -> None:
        event = asyncio.Event()
        self._events[project_id] = event
        task = asyncio.create_task(
            self._run(project_id, run_no, event), name=f"ase-project-{project_id}"
        )
        self._tasks[project_id] = task

        def _cleanup(done: asyncio.Task[None]) -> None:
            if self._tasks.get(project_id) is done:
                self._tasks.pop(project_id, None)
            if self._events.get(project_id) is event:
                self._events.pop(project_id, None)

        task.add_done_callback(_cleanup)

    async def cancel(self, project_id: int, *, wait: bool = False) -> None:
        event = self._events.get(project_id)
        if event is not None:
            event.set()
        task = self._tasks.get(project_id)
        if task is not None and not task.done():
            task.cancel()
            if wait:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        sampler = self._samplers.pop(project_id, None)
        if sampler is not None:
            sampler.cancel()

    async def shutdown(self) -> None:
        for project_id in list(self._tasks):
            await self.cancel(project_id, wait=True)

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    async def _run(
        self, project_id: int, run_no: int, cancel_event: asyncio.Event
    ) -> None:
        runtime: SandboxRuntime | None = None
        manager: SandboxManager | None = None
        sampler_task: asyncio.Task[None] | None = None
        try:
            if cancel_event.is_set():
                return
            project = await self._load_project(project_id)
            if project is None:
                return
            config = await get_raw_config()
            llm_runtime = LLMRuntime.from_config(config)
            state = RunState(
                project_id=project.id,
                run_no=run_no,
                project_name=project.project_name,
                task_content=project.task_content,
                source_path=project.source_path,
            )

            await add_log(
                project_id,
                "info",
                f"第 {run_no} 轮任务启动（项目：{project.project_name}）",
            )
            if llm_runtime.active:
                await add_log(
                    project_id,
                    "info",
                    f"LLM 模式启用：model={llm_runtime.model}",
                )
                await add_chat(
                    project_id,
                    "system",
                    "system",
                    f"本轮使用 LLM 模式（模型：{llm_runtime.model}）。",
                )
            else:
                await add_log(
                    project_id,
                    "info",
                    f"规则引擎模式：{llm_runtime.reason}",
                )
                await add_chat(
                    project_id,
                    "system",
                    "system",
                    f"本轮使用规则引擎模式：{llm_runtime.reason}。",
                )

            # ---------- 准备隔离环境 ----------
            try:
                runtime, manager = await self._prepare_environment(
                    project, run_no, config
                )
                if cancel_event.is_set():
                    raise asyncio.CancelledError
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                message = sanitize(str(exc))
                await self._fail(
                    project_id,
                    run_no,
                    f"隔离环境准备失败：{message}",
                    forced_stage="environment_scan",
                )
                return

            # 工具层与运行状态共享同一条调用轨迹
            tools = ToolExecutor(runtime, trace=state.tool_trace)

            # ---------- 阶段编排 ----------
            # 两种引擎共用同一组 hooks，保证数据库、WS 与日志语义一致
            stage_timeout = int(config.get("runtime.stage_timeout_minutes", 15)) * 60

            async def begin_stage(stage_name: str) -> int:
                if cancel_event.is_set():
                    raise asyncio.CancelledError
                stage = await self._get_stage(project_id, run_no, stage_name)
                if stage is None:
                    await self._fail(
                        project_id, run_no, f"阶段记录缺失：{stage_name}"
                    )
                    raise RunAborted(stage_name)
                state.enter_stage(stage_name, stage.id)
                started = now_utc()
                async with SessionLocal() as db:
                    row = await db.get(RuntimeStage, stage.id)
                    row.stage_status = "running"
                    row.started_at = started
                    await db.commit()
                await self._publish_stage(
                    project_id, stage.id, stage_name, "running", run_no
                )
                await add_log(
                    project_id,
                    "info",
                    f"阶段开始：{stage_name}",
                    stage_id=stage.id,
                )
                return stage.id

            async def execute_stage(stage_name: str, stage_id: int) -> None:
                try:
                    await asyncio.wait_for(
                        self._run_stage(
                            project,
                            run_no,
                            stage_id,
                            stage_name,
                            runtime,
                            config,
                            llm_runtime,
                            state,
                            tools,
                        ),
                        timeout=stage_timeout,
                    )
                except asyncio.TimeoutError:
                    await self._mark_stage_workers_failed(stage_id, "stage timeout")
                    await self._finish_stage(
                        stage_id, "failed", error_message="stage timeout"
                    )
                    await self._publish_stage(
                        project_id, stage_id, stage_name, "failed", run_no
                    )
                    await add_log(
                        project_id,
                        "error",
                        f"阶段超时：{stage_name}（{stage_timeout} 秒）",
                        stage_id=stage_id,
                    )
                    raise StageAborted(
                        f"阶段 {stage_name} 超时", stage_id, stage_name
                    ) from None
                except WorkerError as exc:
                    await self._finish_stage(
                        stage_id, "failed", error_message=str(exc)
                    )
                    await self._publish_stage(
                        project_id, stage_id, stage_name, "failed", run_no
                    )
                    await add_log(
                        project_id,
                        "error",
                        f"阶段失败：{stage_name}：{exc}",
                        stage_id=stage_id,
                    )
                    raise StageAborted(
                        f"阶段 {stage_name} 失败：{exc}", stage_id, stage_name
                    ) from exc
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.exception("stage %s failed unexpectedly", stage_name)
                    await self._finish_stage(
                        stage_id, "failed", error_message=str(exc)
                    )
                    await self._publish_stage(
                        project_id, stage_id, stage_name, "failed", run_no
                    )
                    raise StageAborted(
                        f"阶段 {stage_name} 异常：{exc}", stage_id, stage_name
                    ) from exc

            async def complete_stage(stage_name: str, stage_id: int) -> None:
                await self._finish_stage(stage_id, "success")
                await self._publish_stage(
                    project_id, stage_id, stage_name, "success", run_no
                )
                await add_log(
                    project_id,
                    "info",
                    f"阶段完成：{stage_name}",
                    stage_id=stage_id,
                )

            async def after_environment_scan() -> None:
                nonlocal sampler_task
                await self._set_env_status(project_id, "running")
                sampler_task = self._start_sampler(
                    project_id, runtime, config, llm_runtime
                )

            async def has_findings() -> bool:
                async with SessionLocal() as db:
                    count = await db.scalar(
                        select(func.count(Vulnerability.id)).where(
                            Vulnerability.project_id == project_id,
                            Vulnerability.run_no == run_no,
                        )
                    )
                return bool(count)

            async def skip_stage(stage_name: str) -> None:
                stage_id = await begin_stage(stage_name)
                await self._finish_stage(stage_id, "success")
                await self._publish_stage(
                    project_id, stage_id, stage_name, "success", run_no
                )
                await add_log(
                    project_id,
                    "warn",
                    f"阶段跳过：{stage_name}（无候选漏洞）",
                    stage_id=stage_id,
                )

            hooks = StageHooks(
                begin=begin_stage,
                execute=execute_stage,
                complete=complete_stage,
                after_environment_scan=after_environment_scan,
                has_findings=has_findings,
                skip_stage=skip_stage,
            )
            engine = str(config.get("orchestration.engine", "fixed")).lower()
            if engine == "langgraph" and LANGGRAPH_AVAILABLE:
                orchestrator = LangGraphOrchestrator()
            else:
                if engine == "langgraph":
                    await add_log(
                        project_id,
                        "warn",
                        "LangGraph 不可用，回退 fixed 编排",
                    )
                orchestrator = FixedOrchestrator()
            await add_log(
                project_id, "info", f"阶段编排引擎：{orchestrator.name}"
            )
            try:
                await orchestrator.run(STAGE_ORDER, hooks)
            except RunAborted:
                return
            except StageAborted as exc:
                await self._fail(
                    project_id,
                    run_no,
                    exc.message,
                    failed_stage_id=exc.stage_id,
                )
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("orchestrator failed unexpectedly")
                await self._fail(project_id, run_no, f"编排异常：{exc}")
                return

            # ---------- 完成判定 ----------
            if cancel_event.is_set():
                raise asyncio.CancelledError

            # 最终资源快照：确保本轮累计 LLM token 落库
            with contextlib.suppress(Exception):
                final_stats = await runtime.stats()
                await add_resource(
                    project_id,
                    final_stats["cpu_usage"],
                    final_stats["memory_usage"],
                    llm_runtime.token_count,
                )

            state.sync_tokens(llm_runtime.token_count)
            state.fallback = not llm_runtime.active
            await add_log(
                project_id,
                "info",
                "运行状态快照：" + json.dumps(state.snapshot(), ensure_ascii=False),
            )

            # FR-EXEC-06：任务结束前清空 tmp，保证 completed 时工作区已清理
            with contextlib.suppress(Exception):
                await cleanup_remote_tmp(project_id, run_no)

            async with SessionLocal() as db:
                report_id = await db.scalar(
                    select(Report.id).where(
                        Report.project_id == project_id, Report.run_no == run_no
                    )
                )
                project_row = await db.get(Project, project_id)
                if report_id is not None:
                    project_row.project_status = "completed"
                    project_row.updated_at = now_utc()
                else:
                    project_row.project_status = "failed"
                    project_row.updated_at = now_utc()
                await db.commit()

            if report_id is not None:
                await self._set_env_status(project_id, "stopped")
                await self._publish_project_status(project_id, "completed", run_no)
                await add_log(project_id, "info", "全部阶段完成，项目状态：completed")
            else:
                await self._set_env_status(project_id, "failed", "报告未生成")
                await self._publish_project_status(project_id, "failed", run_no)
                await add_log(project_id, "error", "四个阶段完成但未生成报告，项目失败")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("project %s run %s crashed", project_id, run_no)
            with contextlib.suppress(Exception):
                await self._fail(project_id, run_no, f"任务异常终止：{exc}")
        finally:
            if sampler_task is not None:
                sampler_task.cancel()
                if self._samplers.get(project_id) is sampler_task:
                    self._samplers.pop(project_id, None)
            if runtime is not None:
                with contextlib.suppress(Exception):
                    await runtime.stop()
                with contextlib.suppress(Exception):
                    await runtime.close()
            elif manager is not None:
                with contextlib.suppress(Exception):
                    await manager.close()
            with contextlib.suppress(Exception):
                await cleanup_remote_tmp(project_id, run_no)

    # ------------------------------------------------------------------
    # 环境准备
    # ------------------------------------------------------------------
    async def _prepare_environment(
        self, project: Project, run_no: int, config: dict[str, Any]
    ) -> tuple[SandboxRuntime, SandboxManager]:
        await self._set_env_status(project.id, "creating")
        await add_log(
            project.id, "info", f"开始同步源码并创建沙箱容器（run_no={run_no}）"
        )
        sync_result = await sync_source(project.id, run_no, project.source_path)
        await add_log(
            project.id,
            "info",
            f"源码同步完成：{sync_result['file_count']} 个文件，"
            f"SHA-256={sync_result['fingerprint']}",
        )

        manager = SandboxManager()
        image = str(config.get("sandbox.image", settings.sandbox_image))
        try:
            # FR-ENV-04：再次启动时先销毁上一轮容器，保留上一轮 VM 工作区
            removed = await manager.remove_project_containers(project.id)
            if removed:
                await add_log(
                    project.id,
                    "info",
                    f"已销毁上一轮沙箱容器：{', '.join(removed)}",
                )
            spec = SandboxSpec(
                project_id=project.id,
                run_no=run_no,
                image=image,
                source_dir_vm=sync_result["source_dir"],
                workspace_dir_vm=sync_result["tmp_dir"],
                config=config,
            )
            name = await manager.create_and_start(spec)
            ready = await manager.wait_ready(name)
            if not ready:
                await manager.remove(name)
                raise ApiError(500, 3001, "沙箱容器未进入 running 状态")
        except BaseException:
            # 包含 CancelledError：释放 Docker 客户端；残留容器由标签清理兜底
            await manager.close()
            raise

        runtime = SandboxRuntime(
            manager=manager,
            container_name=name,
            image=image,
            source_dir_vm=sync_result["source_dir"],
            workspace_dir_vm=sync_result["tmp_dir"],
            config=config,
            project_id=project.id,
        )
        await self._set_env_status(project.id, "ready", env_ref=name)
        await add_log(
            project.id, "info", f"沙箱容器已启动：{name}（镜像 {image}）"
        )
        return runtime, manager

    async def _load_project(self, project_id: int) -> Project | None:
        async with SessionLocal() as db:
            return await db.get(Project, project_id)

    async def _get_stage(
        self, project_id: int, run_no: int, stage_name: str
    ) -> RuntimeStage | None:
        async with SessionLocal() as db:
            return await db.scalar(
                select(RuntimeStage).where(
                    RuntimeStage.project_id == project_id,
                    RuntimeStage.run_no == run_no,
                    RuntimeStage.stage_name == stage_name,
                )
            )

    # ------------------------------------------------------------------
    # 阶段与角色
    # ------------------------------------------------------------------
    async def _run_stage(
        self,
        project: Project,
        run_no: int,
        stage_id: int,
        stage_name: str,
        runtime: SandboxRuntime,
        config: dict[str, Any],
        llm_runtime: LLMRuntime,
        state: RunState,
        tools: ToolExecutor,
    ) -> None:
        for role, is_main in STAGE_ROLES[stage_name]:
            task_content = (
                f"项目「{project.project_name}」第 {run_no} 轮，阶段 {stage_name}，"
                f"角色 {role}。任务说明：{project.task_content}"
            )
            async with SessionLocal() as db:
                worker = WorkerTask(
                    project_id=project.id,
                    stage_id=stage_id,
                    worker_role=role,
                    task_content=task_content,
                    task_status="running",
                    started_at=now_utc(),
                )
                db.add(worker)
                await db.commit()
                await db.refresh(worker)
                worker_id = worker.id

            # 命令审计（FR-EXEC-05）使用当前阶段与角色
            tools.bind_worker(stage_id, worker_id)
            state.bind_worker(worker_id)
            await publish(
                project.id,
                "worker_status",
                {
                    "worker_task_id": worker_id,
                    "worker_role": role,
                    "task_status": "running",
                    "stage_id": stage_id,
                    "project_id": project.id,
                },
            )
            await add_log(
                project.id,
                "info",
                f"角色开始：{role}",
                stage_id=stage_id,
                worker_task_id=worker_id,
            )

            ctx = WorkerContext(
                project_id=project.id,
                project_name=project.project_name,
                task_content=project.task_content,
                run_no=run_no,
                stage_id=stage_id,
                stage_name=stage_name,
                worker_task_id=worker_id,
                sandbox=runtime,
                config=config,
                source_path=project.source_path,
                llm=llm_runtime,
                state=state,
                tools=tools,
            )
            try:
                summary = await run_worker(role, ctx)
            except Exception as exc:  # noqa: BLE001
                message = sanitize(str(exc))[:2000]
                if is_main:
                    state.fail(message)
                state.sync_tokens(ctx.llm.token_count)
                state.fallback = not ctx.llm.active
                await self._finish_worker(
                    worker_id, "failed", error_message=message
                )
                await publish(
                    project.id,
                    "worker_status",
                    {
                        "worker_task_id": worker_id,
                        "worker_role": role,
                        "task_status": "failed",
                        "stage_id": stage_id,
                        "project_id": project.id,
                    },
                )
                await add_log(
                    project.id,
                    "error",
                    f"角色失败：{role}：{message}",
                    stage_id=stage_id,
                    worker_task_id=worker_id,
                )
                if is_main:
                    raise WorkerError(f"主角色 {role} 执行失败：{message}") from exc
                continue

            state.sync_tokens(ctx.llm.token_count)
            state.fallback = not ctx.llm.active
            if role == "general" and isinstance(summary, dict):
                state.record_plan(summary)
            elif (
                role == "code_analyst"
                and stage_name == "code_analysis"
                and isinstance(summary, dict)
            ):
                state.record_findings(list(summary.get("vuln_codes") or []))

            summary_text = json.dumps(summary, ensure_ascii=False)[:4000]
            await self._finish_worker(
                worker_id, "success", result_summary=summary_text
            )
            await publish(
                project.id,
                "worker_status",
                {
                    "worker_task_id": worker_id,
                    "worker_role": role,
                    "task_status": "success",
                    "stage_id": stage_id,
                    "project_id": project.id,
                },
            )
            await add_log(
                project.id,
                "info",
                f"角色完成：{role} {summary_text[:300]}",
                stage_id=stage_id,
                worker_task_id=worker_id,
            )

    async def _finish_worker(
        self,
        worker_id: int,
        status: str,
        *,
        result_summary: str | None = None,
        error_message: str | None = None,
    ) -> None:
        async with SessionLocal() as db:
            worker = await db.get(WorkerTask, worker_id)
            if worker is None:
                return
            worker.task_status = status
            worker.result_summary = result_summary
            worker.error_message = error_message
            worker.finished_at = now_utc()
            await db.commit()

    async def _mark_stage_workers_failed(self, stage_id: int, message: str) -> None:
        async with SessionLocal() as db:
            await db.execute(
                update(WorkerTask)
                .where(
                    WorkerTask.stage_id == stage_id,
                    WorkerTask.task_status == "running",
                )
                .values(
                    task_status="failed",
                    error_message=message,
                    finished_at=now_utc(),
                )
            )
            await db.commit()

    async def _finish_stage(
        self, stage_id: int, status: str, *, error_message: str | None = None
    ) -> None:
        async with SessionLocal() as db:
            stage = await db.get(RuntimeStage, stage_id)
            if stage is None:
                return
            stage.stage_status = status
            stage.finished_at = now_utc()
            stage.error_message = error_message
            await db.commit()

    # ------------------------------------------------------------------
    # 失败、状态与采样
    # ------------------------------------------------------------------
    async def _fail(
        self,
        project_id: int,
        run_no: int,
        message: str,
        *,
        failed_stage_id: int | None = None,
        forced_stage: str | None = None,
    ) -> None:
        now = now_utc()
        async with SessionLocal() as db:
            project = await db.get(Project, project_id)
            if project is not None:
                project.project_status = "failed"
                project.updated_at = now
            stages = (
                (
                    await db.execute(
                        select(RuntimeStage).where(
                            RuntimeStage.project_id == project_id,
                            RuntimeStage.run_no == run_no,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for stage in stages:
                if failed_stage_id is not None and stage.id == failed_stage_id:
                    stage.stage_status = "failed"
                    stage.finished_at = now
                    stage.error_message = message
                elif forced_stage is not None and stage.stage_name == forced_stage:
                    stage.stage_status = "failed"
                    stage.finished_at = now
                    stage.error_message = message
                elif stage.stage_status == "running":
                    stage.stage_status = "failed"
                    stage.finished_at = now
                    stage.error_message = message
                elif stage.stage_status == "pending":
                    stage.stage_status = "cancelled"
            await db.execute(
                update(WorkerTask)
                .where(
                    WorkerTask.project_id == project_id,
                    WorkerTask.task_status == "running",
                )
                .values(
                    task_status="failed",
                    error_message=message[:2000],
                    finished_at=now,
                )
            )
            env = await db.scalar(
                select(IsolationEnv).where(IsolationEnv.project_id == project_id)
            )
            if env is not None:
                env.env_status = "failed"
                env.last_error = message[:2000]
                env.updated_at = now
            await db.commit()

            stage_snapshot = [
                (stage.id, stage.stage_name, stage.stage_status) for stage in stages
            ]

        for stage_id, stage_name, stage_status in stage_snapshot:
            await self._publish_stage(
                project_id, stage_id, stage_name, stage_status, run_no
            )
        await self._publish_project_status(project_id, "failed", run_no)
        await add_log(project_id, "error", message)

    async def _set_env_status(
        self,
        project_id: int,
        status: str,
        *,
        error: str | None = None,
        env_ref: str | None = None,
    ) -> None:
        async with SessionLocal() as db:
            env = await db.scalar(
                select(IsolationEnv).where(IsolationEnv.project_id == project_id)
            )
            if env is None:
                return
            env.env_status = status
            env.updated_at = now_utc()
            if error is not None:
                env.last_error = error[:2000]
            if env_ref is not None:
                env.env_ref = env_ref
            await db.commit()

    async def _publish_stage(
        self,
        project_id: int,
        stage_id: int,
        stage_name: str,
        status: str,
        run_no: int,
    ) -> None:
        await publish(
            project_id,
            "stage_status",
            {
                "project_id": project_id,
                "stage_id": stage_id,
                "stage_name": stage_name,
                "stage_status": status,
                "run_no": run_no,
            },
        )

    async def _publish_project_status(
        self, project_id: int, status: str, run_no: int
    ) -> None:
        await publish(
            project_id,
            "project_status",
            {
                "project_id": project_id,
                "project_status": status,
                "run_no": run_no,
                "updated_at": cn_time(now_utc()),
            },
        )

    def _start_sampler(
        self,
        project_id: int,
        runtime: SandboxRuntime,
        config: dict[str, Any],
        llm_runtime: LLMRuntime,
    ) -> asyncio.Task[None]:
        interval = int(config.get("runtime.resource_sample_seconds", 5))
        task = asyncio.create_task(
            self._sample_loop(project_id, runtime, interval, llm_runtime),
            name=f"ase-sampler-{project_id}",
        )
        self._samplers[project_id] = task
        return task

    async def _sample_loop(
        self,
        project_id: int,
        runtime: SandboxRuntime,
        interval: int,
        llm_runtime: LLMRuntime,
    ) -> None:
        try:
            while True:
                stats = await runtime.stats()
                await add_resource(
                    project_id,
                    stats["cpu_usage"],
                    stats["memory_usage"],
                    llm_runtime.token_count,
                )
                await asyncio.sleep(max(1, interval))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("resource sampling stopped for %s: %s", project_id, exc)


scheduler = Scheduler()
