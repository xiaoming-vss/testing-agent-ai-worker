"""Worker object assembly and runtime helpers."""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from testing_agent_ai_worker.config.loader import load_settings
from testing_agent_ai_worker.config.models import Settings
from testing_agent_ai_worker.platform.http_client import PlatformHttpClient
from testing_agent_ai_worker.platform.result_sink import HttpResultSink
from testing_agent_ai_worker.platform.task_source import HttpClaimTaskSource
from testing_agent_ai_worker.services.result_service import ResultService
from testing_agent_ai_worker.services.task_service import TaskService
from testing_agent_ai_worker.tasks.api_case_generate.executor import ApiCaseNanobotExecutor
from testing_agent_ai_worker.tasks.code_risk_analysis.executor import (
    CodeRiskAnalysisNanobotExecutor,
)
from testing_agent_ai_worker.tasks.functional_case_generate.executor import (
    FunctionalCaseNanobotExecutor,
)
from testing_agent_ai_worker.tasks.requirement_analysis.executor import (
    RequirementAnalysisNanobotExecutor,
)
from testing_agent_ai_worker.tasks.requirement_analysis.source_downloader import (
    PlatformRequirementSourceDownloader,
)
from testing_agent_ai_worker.tasks.test_report_generate.executor import TestReportNanobotExecutor
from testing_agent_ai_worker.tasks.ui_case_generate.executor import UiCaseNanobotExecutor
from testing_agent_ai_worker.tasks.ui_case_generate.source_archive import (
    PlatformSourceArchiveDownloader,
)
from testing_agent_ai_worker.worker.dispatcher import WorkerTaskDispatcherExecutor
from testing_agent_ai_worker.worker.lifecycle import WorkerLifecycle
from testing_agent_ai_worker.worker.loop import run_worker_loop
from testing_agent_ai_worker.worker.poller import TaskPoller
from testing_agent_ai_worker.worker.runner import WorkerRunner


def build_task_poller(settings: Settings) -> TaskPoller:
    """组装任务获取链路。"""

    if not settings.platform.base_url:
        raise ValueError("platform.base_url is required")

    client = PlatformHttpClient(
        base_url=settings.platform.base_url,
        worker_token=settings.platform.worker_token,
        timeout_seconds=settings.platform.request_timeout_seconds,
    )
    task_source = HttpClaimTaskSource(
        client=client,
        claim_path=settings.platform.task_claim_path,
        snapshot_path_template=settings.platform.task_snapshot_path,
        llm_credentials_path_template=settings.platform.task_llm_credentials_path,
        worker_id=settings.worker.worker_id,
    )
    return TaskPoller(TaskService(task_source))


def build_task_runner(
    settings: Settings,
    *,
    client: PlatformHttpClient | None = None,
) -> WorkerRunner:
    """组装任务执行链路。"""

    resolved_client = client or PlatformHttpClient(
        base_url=settings.platform.base_url,
        worker_token=settings.platform.worker_token,
        timeout_seconds=settings.platform.request_timeout_seconds,
    )
    result_sink = HttpResultSink(
        client=resolved_client,
        worker_id=settings.worker.worker_id,
        started_path_template=settings.platform.task_started_path,
        heartbeat_path_template=settings.platform.task_heartbeat_path,
        progress_path_template=settings.platform.task_progress_path,
        completed_path_template=settings.platform.task_completed_path,
    )
    return WorkerRunner(
        executor=WorkerTaskDispatcherExecutor(
            api_executor=ApiCaseNanobotExecutor(
                nanobot_config=settings.nanobot,
            ),
            functional_executor=FunctionalCaseNanobotExecutor(
                nanobot_config=settings.nanobot,
            ),
            requirement_executor=RequirementAnalysisNanobotExecutor(
                nanobot_config=settings.nanobot,
                source_downloader=PlatformRequirementSourceDownloader(resolved_client),
            ),
            test_report_executor=TestReportNanobotExecutor(
                nanobot_config=settings.nanobot,
            ),
            ui_executor=UiCaseNanobotExecutor(
                nanobot_config=settings.nanobot,
                source_downloader=PlatformSourceArchiveDownloader(resolved_client),
            ),
            code_risk_executor=CodeRiskAnalysisNanobotExecutor(
                nanobot_config=settings.nanobot,
                client=resolved_client,
                timeout_seconds=settings.code_risk_analysis.gitlab_timeout_seconds,
            ),
        ),
        result_service=ResultService(result_sink),
        lifecycle=WorkerLifecycle(
            poll_interval_seconds=settings.worker.poll_interval_seconds,
            heartbeat_interval_seconds=settings.worker.heartbeat_interval_seconds,
            run_once=settings.worker.run_once,
        ),
    )


def run_poll_once(
    *,
    settings: Settings | None = None,
    config_path: str | Path | None = None,
    poller: TaskPoller | None = None,
    printer: Callable[[str], None] = print,
) -> int:
    """执行一次 claim/snapshot 轮询，主要用于本地调试平台取任务链路。"""

    resolved_settings = settings or load_settings(config_path)
    resolved_poller = poller or build_task_poller(resolved_settings)

    task = resolved_poller.poll()
    if task is None:
        printer("no task claimed")
        return 0

    printer(
        "claimed task "
        f"{task.task_id} "
        f"type={task.task_type} "
        f"project={task.project_id} "
        f"sprint={task.sprint_id} "
        f"requirement={task.requirement_id}"
    )
    if task.credential_error:
        printer(f"llm credentials unavailable: {task.credential_error}")
    return 0


def run_worker(
    *,
    settings: Settings | None = None,
    config_path: str | Path | None = None,
    poller: TaskPoller | None = None,
    task_runner: WorkerRunner | None = None,
    printer: Callable[[str], None] = print,
    sleep: Callable[[int], None] | None = None,
    logger: logging.Logger | None = None,
    max_iterations: int | None = None,
) -> int:
    """运行 worker 主循环。"""

    resolved_settings = settings or load_settings(config_path)
    _apply_nanobot_runtime_environment(resolved_settings)
    resolved_poller = poller or build_task_poller(resolved_settings)
    resolved_task_runner = task_runner or build_task_runner(resolved_settings)
    resolved_logger = logger or logging.getLogger("testing_agent_ai_worker")

    max_concurrent_tasks = max(1, resolved_settings.worker.max_concurrent_tasks)
    free_slots = threading.Semaphore(max_concurrent_tasks)
    task_pool = ThreadPoolExecutor(
        max_workers=max_concurrent_tasks, thread_name_prefix="task-worker"
    )

    try:
        return run_worker_loop(
            settings=resolved_settings,
            poller=resolved_poller,
            run_iteration=lambda: _run_worker_iteration(
                poller=resolved_poller,
                task_runner=resolved_task_runner,
                printer=printer,
                task_pool=task_pool,
                free_slots=free_slots,
            ),
            sleep=sleep or time.sleep,
            logger=resolved_logger,
            max_iterations=max_iterations,
        )
    finally:
        # 循环正常退出(run_once / 测试轮数上限)时排空在途任务;
        # SIGTERM 直接终止进程,不会走到这里(ADR 0003)。
        task_pool.shutdown(wait=True)


def _apply_nanobot_runtime_environment(settings: Settings) -> None:
    llm_timeout_seconds = settings.nanobot.llm_timeout_seconds
    if llm_timeout_seconds is not None:
        os.environ["NANOBOT_LLM_TIMEOUT_S"] = f"{llm_timeout_seconds:g}"

    provider_request_timeout_seconds = settings.nanobot.provider_request_timeout_seconds
    if provider_request_timeout_seconds is not None:
        os.environ["NANOBOT_OPENAI_COMPAT_TIMEOUT_S"] = f"{provider_request_timeout_seconds:g}"


def _run_worker_iteration(
    *,
    poller: TaskPoller,
    task_runner: WorkerRunner,
    printer: Callable[[str], None],
    task_pool: ThreadPoolExecutor,
    free_slots: threading.Semaphore,
) -> bool:
    """执行单轮 worker 迭代,返回本轮是否认领到任务。认领后提交即返回。"""

    if not free_slots.acquire(blocking=False):
        printer("worker at max concurrency, waiting for a free slot")
        return False

    try:
        task = poller.poll()
    except Exception:
        free_slots.release()
        raise

    if task is None:
        free_slots.release()
        printer("no task claimed")
        return False

    printer(
        "claimed task "
        f"{task.task_id} "
        f"type={task.task_type} "
        f"project={task.project_id} "
        f"sprint={task.sprint_id} "
        f"requirement={task.requirement_id}"
    )
    try:
        future = task_pool.submit(task_runner.process_task, task)
    except Exception:
        free_slots.release()
        raise

    def _release_slot(completed_future) -> None:
        # 消费一次异常,避免「exception was never retrieved」告警。
        completed_future.exception()
        free_slots.release()

    future.add_done_callback(_release_slot)
    return True
