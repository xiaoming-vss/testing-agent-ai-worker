"""Task execution lifecycle runner.

调用链路：
- `main._run_worker_iteration -> WorkerRunner.process_task`
- `process_task -> mark_started -> heartbeat thread -> executor.execute`
- `process_task -> submit_progress / submit completed`

这里把平台生命周期回调和真正的业务执行器串成一个完整闭环。
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime

from testing_agent_ai_worker.models.execution import TaskProgress, TaskResult, TaskStatus
from testing_agent_ai_worker.models.task import Task
from testing_agent_ai_worker.services.result_service import ResultService
from testing_agent_ai_worker.worker.lifecycle import WorkerLifecycle

LOGGER = logging.getLogger(__name__)


class TaskExecutor:
    """执行器协议。

    返回 `TaskResult` 表示本轮应提交 completed；
    返回 `None` 表示任务停在 checkpoint 中间阶段，只提交 progress。
    """

    def execute(
        self,
        task: Task,
        started_at: datetime,
        progress_callback: Callable[[TaskProgress], None],
    ) -> TaskResult | None: ...


class WorkerRunner:
    """生命周期执行编排器。"""

    def __init__(
        self,
        *,
        executor: TaskExecutor,
        result_service: ResultService,
        lifecycle: WorkerLifecycle,
    ) -> None:
        self.executor = executor
        self.result_service = result_service
        self.lifecycle = lifecycle

    def process_task(self, task: Task) -> TaskResult | None:
        """执行单个任务并维护 started/heartbeat/completed。

        这里不关心具体业务类型，只负责统一生命周期包装。
        """

        started_at = datetime.now().astimezone()
        stop_event = threading.Event()
        heartbeat_thread: threading.Thread | None = None
        latest_progress: TaskProgress | None = None

        def submit_progress(progress: TaskProgress) -> None:
            nonlocal latest_progress
            latest_progress = progress
            try:
                self.result_service.submit_progress(progress)
            except Exception:
                LOGGER.warning(
                    "progress submission failed: task_id=%s stage=%s",
                    progress.task_id,
                    progress.current_stage,
                    exc_info=True,
                )

        # 凭证缺失属于执行前失败，直接回传 failed，不进入 started/heartbeat。
        if task.credential_error:
            result = TaskResult(
                task_id=task.task_id,
                run_id=task.run_id,
                generate_task_id=task.generate_task_id,
                status=TaskStatus.FAILED,
                intermediate_json_text=task.config_json,
                error_message=f"获取 LLM 凭证失败: {task.credential_error}",
                started_at=started_at,
                finished_at=started_at,
            )
            self.result_service.submit(result)
            return result

        try:
            self.result_service.mark_started(task.task_id, started_at.isoformat())
            heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop,
                args=(task, stop_event),
                daemon=True,
            )
            heartbeat_thread.start()

            result = self.executor.execute(
                task,
                started_at,
                submit_progress,
            )
        except Exception as exc:
            intermediate_json_text = (
                latest_progress.intermediate_json_text
                if latest_progress is not None
                else task.config_json
            )
            result = TaskResult(
                task_id=task.task_id,
                run_id=task.run_id,
                generate_task_id=task.generate_task_id,
                status=TaskStatus.ERROR,
                intermediate_json_text=intermediate_json_text,
                output_yaml=latest_progress.output_yaml if latest_progress is not None else "",
                result_summary_json=(
                    latest_progress.result_summary_json if latest_progress is not None else ""
                ),
                error_message=str(exc),
                started_at=started_at,
                finished_at=datetime.now().astimezone(),
            )
        finally:
            stop_event.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=1)

        # checkpoint 中间阶段会返回 None，此时只允许平台看到 progress，不提交 completed。
        if result is not None:
            self.result_service.submit(result)
        return result

    def _heartbeat_loop(self, task: Task, stop_event: threading.Event) -> None:
        """后台心跳续租循环。"""

        interval_seconds = self.lifecycle.heartbeat_interval_for(task.lease_seconds)
        while not stop_event.wait(interval_seconds):
            try:
                self.result_service.send_heartbeat(
                    task.task_id,
                    datetime.now().astimezone().isoformat(),
                )
            except Exception:
                time.sleep(1)
