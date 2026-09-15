import sys
import threading
import unittest
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from testing_agent_ai_worker.models.execution import TaskProgress, TaskResult, TaskStatus
from testing_agent_ai_worker.models.task import Task, TaskPayload
from testing_agent_ai_worker.platform.result_sink import ResultSink
from testing_agent_ai_worker.services.result_service import ResultService
from testing_agent_ai_worker.worker.lifecycle import WorkerLifecycle
from testing_agent_ai_worker.worker.runner import TaskExecutor, WorkerRunner


class _RecordingSink(ResultSink):
    def __init__(self) -> None:
        self.started_calls: list[tuple[str, str]] = []
        self.heartbeat_calls: list[tuple[str, str]] = []
        self.progress_calls: list[TaskProgress] = []
        self.result_calls: list[TaskResult] = []
        self.first_heartbeat = threading.Event()

    def mark_started(self, task_id: str, started_at_iso: str) -> None:
        self.started_calls.append((task_id, started_at_iso))

    def send_heartbeat(self, task_id: str, heartbeat_at_iso: str) -> None:
        self.heartbeat_calls.append((task_id, heartbeat_at_iso))
        self.first_heartbeat.set()

    def submit_progress(self, progress: TaskProgress) -> None:
        self.progress_calls.append(progress)

    def submit_result(self, result: TaskResult) -> None:
        self.result_calls.append(result)


class _FailingProgressSink(_RecordingSink):
    def submit_progress(self, progress: TaskProgress) -> None:
        raise RuntimeError("progress endpoint unavailable")


class _SuccessfulExecutor(TaskExecutor):
    def execute(self, task: Task, started_at: datetime, progress_callback) -> TaskResult:
        progress_callback(
            TaskProgress(
                task_id=task.task_id,
                run_id=task.run_id,
                current_stage="openapi_extract",
                stage_status="running",
                intermediate_json_text='{"cases":[]}',
                result_summary_json='{"status":"running"}',
            )
        )
        return TaskResult(
            task_id=task.task_id,
            run_id=task.run_id,
            generate_task_id=task.generate_task_id,
            status=TaskStatus.SUCCESS,
            intermediate_json_text='{"cases":[]}',
            output_yaml="cases: []",
            result_summary_json='{"status":"success"}',
            started_at=started_at,
            finished_at=datetime.now().astimezone(),
        )


class _HeartbeatAwareExecutor(TaskExecutor):
    def __init__(self, sink: _RecordingSink) -> None:
        self.sink = sink

    def execute(self, task: Task, started_at: datetime, progress_callback) -> TaskResult:
        self.sink.first_heartbeat.wait(timeout=2.0)
        return TaskResult(
            task_id=task.task_id,
            run_id=task.run_id,
            generate_task_id=task.generate_task_id,
            status=TaskStatus.SUCCESS,
            started_at=started_at,
            finished_at=datetime.now().astimezone(),
        )


class _ExplodingExecutor(TaskExecutor):
    def execute(self, task: Task, started_at: datetime, progress_callback) -> TaskResult:
        raise RuntimeError("executor boom")


class _ProgressThenExplodingExecutor(TaskExecutor):
    def execute(self, task: Task, started_at: datetime, progress_callback) -> TaskResult:
        progress_callback(
            TaskProgress(
                task_id=task.task_id,
                run_id=task.run_id,
                current_stage="case_names",
                stage_status="running",
                intermediate_json_text='{"enhancedText":"progress text","caseNames":[]}',
                output_yaml='{"cases":[]}',
                result_summary_json='{"status":"running","stage":"case_names"}',
            )
        )
        raise RuntimeError("executor boom after progress")


class _CheckpointPauseExecutor(TaskExecutor):
    def execute(self, task: Task, started_at: datetime, progress_callback) -> None:
        progress_callback(
            TaskProgress(
                task_id=task.task_id,
                run_id=task.run_id,
                current_stage="requirement_analysis",
                stage_status="waiting_review",
                intermediate_json_text='{"enhancedText":"text"}',
                output_yaml='{"cases":[]}',
                result_summary_json='{"status":"running"}',
            )
        )
        return None


class WorkerRunnerTests(unittest.TestCase):
    def _make_task(self) -> Task:
        return Task(
            task_id="task-1",
            run_id="run-1",
            generate_task_id="generate-1",
            task_type="api_case_generate",
            lease_seconds=1,
            config_json='{"enhancedText":"snapshot text"}',
            payload=TaskPayload(openapi_content="{}", source_content="{}"),
        )

    def test_process_task_marks_started_submits_progress_and_completed(self) -> None:
        sink = _RecordingSink()
        runner = WorkerRunner(
            executor=_SuccessfulExecutor(),
            result_service=ResultService(sink),
            lifecycle=WorkerLifecycle(
                poll_interval_seconds=10,
                heartbeat_interval_seconds=60,
                run_once=False,
            ),
        )

        result = runner.process_task(self._make_task())

        self.assertEqual(len(sink.started_calls), 1)
        self.assertEqual(len(sink.progress_calls), 1)
        self.assertEqual(len(sink.result_calls), 1)
        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertEqual(sink.progress_calls[0].current_stage, "openapi_extract")

    def test_process_task_continues_when_progress_submission_fails(self) -> None:
        sink = _FailingProgressSink()
        runner = WorkerRunner(
            executor=_SuccessfulExecutor(),
            result_service=ResultService(sink),
            lifecycle=WorkerLifecycle(
                poll_interval_seconds=10,
                heartbeat_interval_seconds=60,
                run_once=False,
            ),
        )

        result = runner.process_task(self._make_task())

        self.assertEqual(TaskStatus.SUCCESS, result.status)
        self.assertEqual(1, len(sink.result_calls))
        self.assertEqual(TaskStatus.SUCCESS, sink.result_calls[0].status)

    def test_process_task_sends_heartbeat_while_executor_is_running(self) -> None:
        sink = _RecordingSink()
        runner = WorkerRunner(
            executor=_HeartbeatAwareExecutor(sink),
            result_service=ResultService(sink),
            lifecycle=WorkerLifecycle(
                poll_interval_seconds=10,
                heartbeat_interval_seconds=1,
                run_once=False,
            ),
        )

        result = runner.process_task(self._make_task())

        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertGreaterEqual(len(sink.heartbeat_calls), 1)

    def test_process_task_turns_executor_error_into_final_error_result(self) -> None:
        sink = _RecordingSink()
        runner = WorkerRunner(
            executor=_ExplodingExecutor(),
            result_service=ResultService(sink),
            lifecycle=WorkerLifecycle(
                poll_interval_seconds=10,
                heartbeat_interval_seconds=60,
                run_once=False,
            ),
        )

        result = runner.process_task(self._make_task())

        self.assertEqual(result.status, TaskStatus.ERROR)
        self.assertEqual(result.error_message, "executor boom")
        self.assertEqual(result.intermediate_json_text, '{"enhancedText":"snapshot text"}')
        self.assertEqual(sink.result_calls[0].status, TaskStatus.ERROR)
        self.assertEqual(
            sink.result_calls[0].intermediate_json_text, '{"enhancedText":"snapshot text"}'
        )

    def test_process_task_preserves_latest_progress_config_when_executor_errors_after_progress(
        self,
    ) -> None:
        sink = _RecordingSink()
        runner = WorkerRunner(
            executor=_ProgressThenExplodingExecutor(),
            result_service=ResultService(sink),
            lifecycle=WorkerLifecycle(
                poll_interval_seconds=10,
                heartbeat_interval_seconds=60,
                run_once=False,
            ),
        )

        result = runner.process_task(self._make_task())

        self.assertEqual(result.status, TaskStatus.ERROR)
        self.assertEqual(result.error_message, "executor boom after progress")
        self.assertEqual(
            result.intermediate_json_text, '{"enhancedText":"progress text","caseNames":[]}'
        )
        self.assertEqual(result.output_yaml, '{"cases":[]}')
        self.assertEqual(result.result_summary_json, '{"status":"running","stage":"case_names"}')

    def test_process_task_submits_failed_result_when_credentials_are_missing(self) -> None:
        sink = _RecordingSink()
        task = self._make_task()
        task.credential_error = "credentials unavailable"
        runner = WorkerRunner(
            executor=_ExplodingExecutor(),
            result_service=ResultService(sink),
            lifecycle=WorkerLifecycle(
                poll_interval_seconds=10,
                heartbeat_interval_seconds=60,
                run_once=False,
            ),
        )

        result = runner.process_task(task)

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("credentials unavailable", result.error_message or "")
        self.assertEqual(sink.started_calls, [])
        self.assertEqual(sink.heartbeat_calls, [])

    def test_process_task_does_not_submit_completed_when_executor_returns_none(self) -> None:
        sink = _RecordingSink()
        runner = WorkerRunner(
            executor=_CheckpointPauseExecutor(),
            result_service=ResultService(sink),
            lifecycle=WorkerLifecycle(
                poll_interval_seconds=10,
                heartbeat_interval_seconds=60,
                run_once=False,
            ),
        )

        result = runner.process_task(self._make_task())

        self.assertIsNone(result)
        self.assertEqual(len(sink.started_calls), 1)
        self.assertEqual(len(sink.progress_calls), 1)
        self.assertEqual(sink.progress_calls[0].stage_status, "waiting_review")
        self.assertEqual(sink.result_calls, [])


if __name__ == "__main__":
    unittest.main()
