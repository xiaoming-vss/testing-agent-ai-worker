"""Test report generation executor."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from testing_agent_ai_worker.config.models import NanobotConfig
from testing_agent_ai_worker.models.execution import TaskProgress, TaskResult, TaskStatus
from testing_agent_ai_worker.models.task import Task
from testing_agent_ai_worker.nanobot_runtime.config_builder import task_config_path
from testing_agent_ai_worker.nanobot_runtime.paths import (
    resolve_runtime_paths,
    resolve_task_workspace,
)
from testing_agent_ai_worker.tasks.functional_case_generate.chain import run_skill_step
from testing_agent_ai_worker.tasks.result_summary import build_task_result_summary
from testing_agent_ai_worker.worker.runner import TaskExecutor

TEST_REPORT_SKILL_NAME = "advanced-test-report-generator"


def _resolve_text_result(result) -> str:
    if hasattr(result, "__await__"):
        resolved = asyncio.run(result)
    else:
        resolved = result
    if not isinstance(resolved, str):
        raise ValueError("test report skill result must be text")
    return resolved


class TestReportNanobotExecutor(TaskExecutor):
    """测试报告生成执行器。"""

    def __init__(
        self,
        *,
        nanobot_config: NanobotConfig,
        skill_runner=run_skill_step,
        skill_name: str = TEST_REPORT_SKILL_NAME,
    ) -> None:
        self.nanobot_config = nanobot_config
        self.runtime_paths = resolve_runtime_paths(nanobot_config)
        self.skill_runner = skill_runner
        self.skill_name = skill_name

    def execute(self, task: Task, started_at: datetime, progress_callback) -> TaskResult:
        """执行测试报告生成。"""

        if task.task_type != "test_report_generate":
            return TaskResult(
                task_id=task.task_id,
                run_id=task.run_id,
                generate_task_id=task.generate_task_id,
                status=TaskStatus.FAILED,
                error_message=f"不支持的任务类型: {task.task_type}",
                started_at=started_at,
                finished_at=datetime.now().astimezone(),
            )

        daily_metrics = self._resolve_daily_metrics(task)
        if not daily_metrics:
            return TaskResult(
                task_id=task.task_id,
                run_id=task.run_id,
                generate_task_id=task.generate_task_id,
                status=TaskStatus.FAILED,
                error_message="test_report_generate 缺少 dailyMetrics",
                started_at=started_at,
                finished_at=datetime.now().astimezone(),
            )

        workspace = resolve_task_workspace(self.nanobot_config, task)

        input_text = json.dumps(daily_metrics, ensure_ascii=False, indent=2)
        progress_callback(
            TaskProgress(
                task_id=task.task_id,
                run_id=task.run_id,
                current_stage="report_generating",
                stage_status="running",
                intermediate_json_text=input_text,
                result_summary_json=self._build_result_summary_json(
                    task=task,
                    status="running",
                    daily_metrics=daily_metrics,
                    report_text="",
                    error_message=None,
                ),
            )
        )

        with task_config_path(nanobot_config=self.nanobot_config, task=task) as config_path:
            report_text = _resolve_text_result(
                self.skill_runner(
                    input_text=input_text,
                    session_key=self._resolve_report_session_key(task),
                    skill_name=self.skill_name,
                    config_path=config_path,
                    workspace=str(workspace),
                    extra_instruction=task.payload.extra_instruction,
                )
            )

        return TaskResult(
            task_id=task.task_id,
            run_id=task.run_id,
            generate_task_id=task.generate_task_id,
            status=TaskStatus.SUCCESS,
            intermediate_json_text=input_text,
            output_yaml=report_text,
            result_summary_json=self._build_result_summary_json(
                task=task,
                status=TaskStatus.SUCCESS,
                daily_metrics=daily_metrics,
                report_text=report_text,
                error_message=None,
            ),
            started_at=started_at,
            finished_at=datetime.now().astimezone(),
        )

    @staticmethod
    def _resolve_report_session_key(task: Task) -> str:
        return task.sprint_id.strip()

    @staticmethod
    def _resolve_daily_metrics(task: Task) -> dict[str, object]:
        if task.payload.daily_metrics:
            return task.payload.daily_metrics
        daily_metrics = task.payload.metadata.get("dailyMetrics", {})
        if isinstance(daily_metrics, dict):
            return daily_metrics
        return {}

    @staticmethod
    def _build_result_summary_json(
        *,
        task: Task,
        status: TaskStatus | str,
        daily_metrics: dict[str, object],
        report_text: str,
        error_message: str | None,
    ) -> str:
        return build_task_result_summary(
            task=task,
            status=status,
            error_message=error_message,
            details={
                "dailyMetricsKeys": sorted(daily_metrics.keys()),
                "reportLength": len(report_text),
            },
        )
