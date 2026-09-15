from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path

from testing_agent_ai_worker.config.models import NanobotConfig
from testing_agent_ai_worker.models.execution import TaskStatus
from testing_agent_ai_worker.models.task import Task, TaskPayload
from testing_agent_ai_worker.tasks.test_report_generate.executor import (
    TEST_REPORT_SKILL_NAME,
    TestReportNanobotExecutor,
)


class _RecordingSkillRunner:
    def __init__(self, output: str = "# 测试报告") -> None:
        self.output = output
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.output


class TestReportNanobotExecutorTest(unittest.TestCase):
    def _task(self, *, daily_metrics: dict[str, object] | None = None) -> Task:
        return Task(
            task_id="task-1",
            run_id="run-1",
            generate_task_id="generate-1",
            task_type="test_report_generate",
            project_id="project-1",
            sprint_id="sprint-1",
            payload=TaskPayload(
                openapi_content="",
                extra_instruction="生成测试报告",
                daily_metrics=daily_metrics or {},
            ),
        )

    def test_execute_passes_only_daily_metrics_to_report_skill(self) -> None:
        daily_metrics = {
            "function": {"total": 497, "pending": 497, "executed": 0},
            "bug": {"total": 8, "resolved": 8},
        }
        skill_runner = _RecordingSkillRunner("测试报告正文")
        executor = TestReportNanobotExecutor(
            nanobot_config=NanobotConfig(runtime_root=str(Path("runtime/test-report"))),
            skill_runner=skill_runner,
        )
        progresses = []

        result = executor.execute(
            self._task(daily_metrics=daily_metrics), datetime.now().astimezone(), progresses.append
        )

        self.assertEqual(TaskStatus.SUCCESS, result.status)
        self.assertEqual("测试报告正文", result.output_yaml)
        self.assertEqual(1, len(progresses))
        self.assertEqual("report_generating", progresses[0].current_stage)
        self.assertEqual(1, len(skill_runner.calls))
        self.assertEqual(TEST_REPORT_SKILL_NAME, skill_runner.calls[0]["skill_name"])
        self.assertEqual("生成测试报告", skill_runner.calls[0]["extra_instruction"])
        self.assertEqual(daily_metrics, json.loads(skill_runner.calls[0]["input_text"]))

    def test_execute_fails_when_daily_metrics_missing(self) -> None:
        skill_runner = _RecordingSkillRunner()
        executor = TestReportNanobotExecutor(
            nanobot_config=NanobotConfig(runtime_root=str(Path("runtime/test-report"))),
            skill_runner=skill_runner,
        )

        result = executor.execute(self._task(), datetime.now().astimezone(), lambda _progress: None)

        self.assertEqual(TaskStatus.FAILED, result.status)
        self.assertEqual("test_report_generate 缺少 dailyMetrics", result.error_message)
        self.assertEqual([], skill_runner.calls)


if __name__ == "__main__":
    unittest.main()
