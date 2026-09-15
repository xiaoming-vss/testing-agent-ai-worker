import sys
import unittest
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from testing_agent_ai_worker.models.execution import TaskResult, TaskStatus
from testing_agent_ai_worker.models.task import Task, TaskPayload
from testing_agent_ai_worker.worker.dispatcher import WorkerTaskDispatcherExecutor


class _FakeExecutor:
    def __init__(self) -> None:
        self.calls = 0
        self.last_task = None

    def execute(self, task, started_at, progress_callback):
        self.calls += 1
        self.last_task = task
        return TaskResult(
            task_id=task.task_id,
            run_id=task.run_id,
            status=TaskStatus.SUCCESS,
            started_at=started_at,
            finished_at=datetime.now().astimezone(),
        )


class WorkerTaskDispatcherCodeRiskTests(unittest.TestCase):
    def _dispatcher(self, code_risk_executor=None) -> WorkerTaskDispatcherExecutor:
        return WorkerTaskDispatcherExecutor(
            api_executor=_FakeExecutor(),
            functional_executor=_FakeExecutor(),
            requirement_executor=_FakeExecutor(),
            test_report_executor=_FakeExecutor(),
            ui_executor=_FakeExecutor(),
            code_risk_executor=code_risk_executor,
        )

    def _task(self, task_type: str = "code_risk_analysis") -> Task:
        return Task(
            task_id="task-1",
            run_id="run-1",
            task_type=task_type,
            project_id="project-1",
            payload=TaskPayload(openapi_content="{}"),
        )

    def test_dispatches_code_risk_analysis_to_configured_executor(self) -> None:
        code_risk_executor = _FakeExecutor()
        dispatcher = self._dispatcher(code_risk_executor=code_risk_executor)

        result = dispatcher.execute(
            self._task("code_risk_analysis"),
            datetime.now().astimezone(),
            lambda _progress: None,
        )

        self.assertEqual(TaskStatus.SUCCESS, result.status)
        self.assertEqual(1, code_risk_executor.calls)
        self.assertEqual("code_risk_analysis", code_risk_executor.last_task.task_type)

    def test_fails_when_code_risk_executor_not_configured(self) -> None:
        dispatcher = self._dispatcher(code_risk_executor=None)

        result = dispatcher.execute(
            self._task("code_risk_analysis"),
            datetime.now().astimezone(),
            lambda _progress: None,
        )

        self.assertEqual(TaskStatus.FAILED, result.status)
        self.assertIn("code_risk_analysis", result.error_message or "")

    def test_other_task_types_do_not_reach_code_risk_executor(self) -> None:
        code_risk_executor = _FakeExecutor()
        dispatcher = self._dispatcher(code_risk_executor=code_risk_executor)

        dispatcher.execute(
            self._task("test_report_generate"), datetime.now().astimezone(), lambda _p: None
        )

        self.assertEqual(0, code_risk_executor.calls)


if __name__ == "__main__":
    unittest.main()
