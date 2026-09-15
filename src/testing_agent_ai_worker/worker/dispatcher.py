"""Task type dispatcher."""

from __future__ import annotations

from datetime import datetime

from testing_agent_ai_worker.models.execution import TaskResult, TaskStatus
from testing_agent_ai_worker.models.task import Task
from testing_agent_ai_worker.worker.runner import TaskExecutor


class WorkerTaskDispatcherExecutor(TaskExecutor):
    """根据 `task_type` 把任务分发到具体执行器。"""

    def __init__(
        self,
        *,
        api_executor: TaskExecutor,
        functional_executor: TaskExecutor,
        requirement_executor: TaskExecutor,
        test_report_executor: TaskExecutor | None = None,
        ui_executor: TaskExecutor | None = None,
        code_risk_executor: TaskExecutor | None = None,
    ) -> None:
        self.api_executor = api_executor
        self.functional_executor = functional_executor
        self.requirement_executor = requirement_executor
        self.test_report_executor = test_report_executor
        self.ui_executor = ui_executor
        self.code_risk_executor = code_risk_executor

    def execute(self, task: Task, started_at: datetime, progress_callback) -> TaskResult:
        """执行任务分发。"""

        if task.task_type == "api_case_generate":
            return self.api_executor.execute(task, started_at, progress_callback)
        if task.task_type == "functional_case_generate":
            return self.functional_executor.execute(task, started_at, progress_callback)
        if task.task_type == "requirement_analysis":
            return self.requirement_executor.execute(task, started_at, progress_callback)
        if task.task_type == "test_report_generate" and self.test_report_executor is not None:
            return self.test_report_executor.execute(task, started_at, progress_callback)
        if task.task_type == "ui_case_generate" and self.ui_executor is not None:
            return self.ui_executor.execute(task, started_at, progress_callback)
        if task.task_type == "code_risk_analysis" and self.code_risk_executor is not None:
            return self.code_risk_executor.execute(task, started_at, progress_callback)
        return TaskResult(
            task_id=task.task_id,
            run_id=task.run_id,
            generate_task_id=task.generate_task_id,
            status=TaskStatus.FAILED,
            error_message=f"不支持的任务类型: {task.task_type}",
            started_at=started_at,
            finished_at=datetime.now().astimezone(),
        )
