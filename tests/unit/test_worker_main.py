import io
import logging
import os
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from testing_agent_ai_worker.config.loader import load_settings
from testing_agent_ai_worker.config.models import (
    CodeRiskAnalysisConfig,
    LoggingConfig,
    NanobotConfig,
    PlatformConfig,
    Settings,
    WorkerConfig,
)
from testing_agent_ai_worker.logging.setup import setup_logging
from testing_agent_ai_worker.main import build_task_runner, run_poll_once, run_worker
from testing_agent_ai_worker.models.task import Task, TaskPayload
from testing_agent_ai_worker.platform.errors import TaskSourceError
import testing_agent_ai_worker.worker.executor as executor_module


class _FakePoller:
    def __init__(self, task: Task | None) -> None:
        self.task = task
        self.called = False

    def poll(self) -> Task | None:
        self.called = True
        return self.task


class _SequencePoller:
    def __init__(self, tasks: list[Task | None]) -> None:
        self.tasks = tasks
        self.calls = 0

    def poll(self) -> Task | None:
        task = self.tasks[self.calls]
        self.calls += 1
        return task


class _FlakyPoller:
    def __init__(self) -> None:
        self.calls = 0

    def poll(self) -> Task | None:
        self.calls += 1
        if self.calls == 1:
            raise TaskSourceError("领取任务失败: Server error '502 Bad Gateway'")
        return None


class _FakeTaskRunner:
    def __init__(self) -> None:
        self.tasks: list[Task] = []

    def process_task(self, task: Task) -> None:
        self.tasks.append(task)


class _SequenceThenIdlePoller:
    """按序返回任务,耗尽后一直返回 None。"""

    def __init__(self, tasks: list[Task]) -> None:
        self.tasks = tasks
        self.calls = 0

    def poll(self) -> Task | None:
        self.calls += 1
        if self.calls <= len(self.tasks):
            return self.tasks[self.calls - 1]
        return None


class _GatedTaskRunner:
    """记录启动/完成的任务,并在任务执行中阻塞直到测试放行。

    阻塞时长必须远大于测试断言的超时,否则串行实现下 runner 自释放后
    循环继续 claim,会让「并行」断言随机转绿。
    """

    def __init__(self, release_event: threading.Event, block_timeout: float = 30.0) -> None:
        self.release_event = release_event
        self.block_timeout = block_timeout
        self._condition = threading.Condition()
        self.started: list[Task] = []
        self.finished: list[Task] = []

    def process_task(self, task: Task) -> None:
        with self._condition:
            self.started.append(task)
            self._condition.notify_all()
        self.release_event.wait(timeout=self.block_timeout)
        with self._condition:
            self.finished.append(task)
            self._condition.notify_all()

    def wait_for_started(self, count: int, timeout: float = 5.0) -> bool:
        with self._condition:
            while len(self.started) < count:
                if not self._condition.wait(timeout=timeout):
                    break
            return len(self.started) >= count

    def wait_for_finished(self, count: int, timeout: float = 5.0) -> bool:
        with self._condition:
            while len(self.finished) < count:
                if not self._condition.wait(timeout=timeout):
                    break
            return len(self.finished) >= count


class WorkerMainTests(unittest.TestCase):
    def test_load_settings_reads_worker_toml_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "worker.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[worker]",
                        'worker_id = "worker-local"',
                        "poll_interval_seconds = 12",
                        "heartbeat_interval_seconds = 15",
                        "max_concurrent_tasks = 3",
                        "run_once = false",
                        "",
                        "[platform]",
                        'base_url = "https://platform.example.com"',
                        'worker_token = "worker-token"',
                        'task_claim_path = "/claim"',
                        'task_snapshot_path = "/tasks/{task_id}/snapshot"',
                        'task_started_path = "/tasks/{task_id}/started"',
                        'task_heartbeat_path = "/tasks/{task_id}/heartbeat"',
                        'task_progress_path = "/tasks/{task_id}/progress"',
                        'task_completed_path = "/tasks/{task_id}/completed"',
                        'task_llm_credentials_path = "/tasks/{task_id}/llm-credentials"',
                        "request_timeout_seconds = 12.5",
                        "",
                        "[nanobot]",
                        'runtime_root = "D:/tmp/nanobot-runtime"',
                        "llm_timeout_seconds = 900",
                        "provider_request_timeout_seconds = 300",
                        "",
                        "[logging]",
                        'level = "INFO"',
                        "console = true",
                        'dir = "logs"',
                        'filename = "worker.log"',
                        "retention_days = 7",
                    ]
                ),
                encoding="utf-8",
            )

            settings = load_settings(config_path)

        self.assertEqual(
            settings,
            Settings(
                worker=WorkerConfig(
                    worker_id="worker-local",
                    poll_interval_seconds=12,
                    heartbeat_interval_seconds=15,
                    max_concurrent_tasks=3,
                    run_once=False,
                ),
                platform=PlatformConfig(
                    base_url="https://platform.example.com",
                    worker_token="worker-token",
                    task_claim_path="/claim",
                    task_snapshot_path="/tasks/{task_id}/snapshot",
                    task_started_path="/tasks/{task_id}/started",
                    task_heartbeat_path="/tasks/{task_id}/heartbeat",
                    task_progress_path="/tasks/{task_id}/progress",
                    task_completed_path="/tasks/{task_id}/completed",
                    task_llm_credentials_path="/tasks/{task_id}/llm-credentials",
                    request_timeout_seconds=12.5,
                ),
                nanobot=NanobotConfig(
                    runtime_root="D:/tmp/nanobot-runtime",
                    llm_timeout_seconds=900,
                    provider_request_timeout_seconds=300,
                ),
                logging=LoggingConfig(
                    level="INFO",
                    console=True,
                    dir="logs",
                    filename="worker.log",
                    retention_days=7,
                ),
            ),
        )

    def test_load_settings_applies_secret_and_runtime_environment_overrides(self) -> None:
        with patch.dict(
            os.environ,
            {
                "TESTING_AGENT_PLATFORM_BASE_URL": "https://platform.runtime.example",
                "TESTING_AGENT_WORKER_TOKEN": "runtime-worker-token",
                "TESTING_AGENT_NANOBOT_RUNTIME_ROOT": "D:/runtime/nanobot",
            },
        ):
            settings = load_settings(PROJECT_ROOT / "config" / "worker.toml")

        self.assertEqual("https://platform.runtime.example", settings.platform.base_url)
        self.assertEqual("runtime-worker-token", settings.platform.worker_token)
        self.assertEqual("D:/runtime/nanobot", settings.nanobot.runtime_root)

    def test_run_poll_once_prints_no_task_when_platform_returns_empty(self) -> None:
        poller = _FakePoller(task=None)
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = run_poll_once(
                settings=Settings(
                    worker=WorkerConfig(),
                    platform=PlatformConfig(base_url="https://platform.example.com"),
                    nanobot=NanobotConfig(runtime_root="D:/tmp/nanobot-runtime"),
                    logging=LoggingConfig(),
                ),
                poller=poller,
            )

        self.assertTrue(poller.called)
        self.assertEqual(exit_code, 0)
        self.assertIn("no task claimed", output.getvalue())

    def test_run_poll_once_prints_claimed_task_summary(self) -> None:
        poller = _FakePoller(
            task=Task(
                task_id="task-1",
                run_id="run-1",
                generate_task_id="generate-1",
                task_type="api_case_generate",
                name="OpenAPI case generation",
                project_id="project-1",
                sprint_id="sprint-1",
                requirement_id="req-1",
                payload=TaskPayload(
                    openapi_content="{}",
                    source_content="{}",
                    source_type="openapi",
                    extra_instruction="only login apis",
                ),
            )
        )
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = run_poll_once(
                settings=Settings(
                    worker=WorkerConfig(),
                    platform=PlatformConfig(base_url="https://platform.example.com"),
                    nanobot=NanobotConfig(runtime_root="D:/tmp/nanobot-runtime"),
                    logging=LoggingConfig(),
                ),
                poller=poller,
            )

        self.assertTrue(poller.called)
        self.assertEqual(exit_code, 0)
        self.assertIn("claimed task task-1", output.getvalue())
        self.assertIn("type=api_case_generate", output.getvalue())

    def test_setup_logging_creates_daily_rotating_file_handler(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logger = setup_logging(
                LoggingConfig(
                    level="INFO",
                    console=True,
                    dir="logs",
                    filename="worker.log",
                    retention_days=7,
                ),
                base_dir=Path(temp_dir),
            )

            log_dir = Path(temp_dir) / "logs"
            handler_types = {type(handler).__name__ for handler in logger.handlers}
            log_dir_exists = log_dir.exists()
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)

        self.assertTrue(log_dir_exists)
        self.assertIn("TimedRotatingFileHandler", handler_types)
        self.assertIn("StreamHandler", handler_types)

    def test_run_worker_loops_by_default_and_sleeps_between_polls(self) -> None:
        task = Task(
            task_id="task-1",
            task_type="api_case_generate",
            payload=TaskPayload(openapi_content="{}", source_content="{}"),
        )
        poller = _SequencePoller([task, None])
        task_runner = _FakeTaskRunner()
        sleep_calls: list[int] = []
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = run_worker(
                settings=Settings(
                    worker=WorkerConfig(poll_interval_seconds=3, run_once=False),
                    platform=PlatformConfig(base_url="https://platform.example.com"),
                    nanobot=NanobotConfig(runtime_root="D:/tmp/nanobot-runtime"),
                    logging=LoggingConfig(),
                ),
                poller=poller,
                task_runner=task_runner,
                sleep=sleep_calls.append,
                max_iterations=2,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(poller.calls, 2)
        self.assertEqual(len(task_runner.tasks), 1)
        self.assertEqual(sleep_calls, [3])

    def test_run_worker_skips_sleep_in_run_once_mode(self) -> None:
        task = Task(
            task_id="task-1",
            task_type="api_case_generate",
            payload=TaskPayload(openapi_content="{}", source_content="{}"),
        )
        poller = _SequencePoller([task])
        task_runner = _FakeTaskRunner()
        sleep_calls: list[int] = []
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = run_worker(
                settings=Settings(
                    worker=WorkerConfig(poll_interval_seconds=3, run_once=True),
                    platform=PlatformConfig(base_url="https://platform.example.com"),
                    nanobot=NanobotConfig(runtime_root="D:/tmp/nanobot-runtime"),
                    logging=LoggingConfig(),
                ),
                poller=poller,
                task_runner=task_runner,
                sleep=sleep_calls.append,
                max_iterations=1,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(poller.calls, 1)
        self.assertEqual(len(task_runner.tasks), 1)
        self.assertEqual(sleep_calls, [])

    def _make_simple_task(self, task_id: str) -> Task:
        return Task(
            task_id=task_id,
            task_type="api_case_generate",
            payload=TaskPayload(openapi_content="{}", source_content="{}"),
        )

    def test_run_worker_claims_up_to_concurrency_limit_without_waiting_for_completion(self) -> None:
        poller = _SequenceThenIdlePoller(
            [self._make_simple_task("task-a"), self._make_simple_task("task-b"), self._make_simple_task("task-c")]
        )
        release_tasks = threading.Event()
        task_runner = _GatedTaskRunner(release_tasks)
        results: list[int] = []
        output = io.StringIO()

        def run_worker_target() -> None:
            with redirect_stdout(output):
                results.append(
                    run_worker(
                        settings=Settings(
                            worker=WorkerConfig(poll_interval_seconds=0, run_once=False, max_concurrent_tasks=2),
                            platform=PlatformConfig(base_url="https://platform.example.com"),
                            nanobot=NanobotConfig(runtime_root="D:/tmp/nanobot-runtime"),
                            logging=LoggingConfig(),
                        ),
                        poller=poller,
                        task_runner=task_runner,
                        sleep=lambda _seconds: time.sleep(0.002),
                        max_iterations=500,
                    )
                )

        worker_thread = threading.Thread(target=run_worker_target, daemon=True)
        worker_thread.start()

        try:
            # 并行:前两个任务被认领并同时在跑,循环不再等待它们完成。
            self.assertTrue(task_runner.wait_for_started(2))
            # 背压:并发槽位占满时,第三个任务不被认领。
            self.assertEqual(2, poller.calls)
        finally:
            release_tasks.set()
        self.assertTrue(task_runner.wait_for_finished(3))
        worker_thread.join(timeout=5)
        self.assertFalse(worker_thread.is_alive())
        self.assertEqual([0], results)
        # 释放槽位后,第三个任务被认领。
        self.assertGreaterEqual(poller.calls, 3)
        self.assertEqual(3, len(task_runner.finished))

    def test_run_once_waits_for_in_flight_task_before_returning(self) -> None:
        release_task = threading.Event()
        task_runner = _GatedTaskRunner(release_task)
        poller = _SequenceThenIdlePoller([self._make_simple_task("task-a")])
        results: list[int] = []
        output = io.StringIO()

        def run_worker_target() -> None:
            with redirect_stdout(output):
                results.append(
                    run_worker(
                        settings=Settings(
                            worker=WorkerConfig(poll_interval_seconds=0, run_once=True, max_concurrent_tasks=2),
                            platform=PlatformConfig(base_url="https://platform.example.com"),
                            nanobot=NanobotConfig(runtime_root="D:/tmp/nanobot-runtime"),
                            logging=LoggingConfig(),
                        ),
                        poller=poller,
                        task_runner=task_runner,
                        sleep=lambda _seconds: None,
                    )
                )

        worker_thread = threading.Thread(target=run_worker_target, daemon=True)
        worker_thread.start()

        try:
            self.assertTrue(task_runner.wait_for_started(1))
            # run_once 必须等在途任务完成才返回,而不是提交后立刻退出。
            self.assertTrue(worker_thread.is_alive())
        finally:
            release_task.set()
        self.assertTrue(task_runner.wait_for_finished(1))
        worker_thread.join(timeout=5)
        self.assertFalse(worker_thread.is_alive())
        self.assertEqual([0], results)

    def test_run_once_claims_a_batch_of_tasks_then_drains(self) -> None:
        release_tasks = threading.Event()
        task_runner = _GatedTaskRunner(release_tasks)
        poller = _SequenceThenIdlePoller(
            [self._make_simple_task("task-a"), self._make_simple_task("task-b"), self._make_simple_task("task-c")]
        )
        results: list[int] = []
        output = io.StringIO()

        def run_worker_target() -> None:
            with redirect_stdout(output):
                results.append(
                    run_worker(
                        settings=Settings(
                            worker=WorkerConfig(poll_interval_seconds=0, run_once=True, max_concurrent_tasks=2),
                            platform=PlatformConfig(base_url="https://platform.example.com"),
                            nanobot=NanobotConfig(runtime_root="D:/tmp/nanobot-runtime"),
                            logging=LoggingConfig(),
                        ),
                        poller=poller,
                        task_runner=task_runner,
                        sleep=lambda _seconds: None,
                    )
                )

        worker_thread = threading.Thread(target=run_worker_target, daemon=True)
        worker_thread.start()

        try:
            # 一批 = 填满并发槽位:主线程断言时刻,槽位未释放前不得多认领。
            self.assertTrue(task_runner.wait_for_started(2))
            self.assertEqual(2, poller.calls)
        finally:
            release_tasks.set()
        self.assertTrue(task_runner.wait_for_finished(2))
        worker_thread.join(timeout=5)
        self.assertFalse(worker_thread.is_alive())
        self.assertEqual([0], results)
        # 排空:凡认领的任务全部完成;「一批」至少两个,但放行快时可能多认领一个。
        self.assertGreaterEqual(len(task_runner.finished), 2)
        self.assertEqual(
            sorted(t.task_id for t in task_runner.started),
            sorted(t.task_id for t in task_runner.finished),
        )

    def test_task_exception_does_not_stop_sibling_tasks(self) -> None:
        class _ExplodingOnBadTaskRunner:
            def __init__(self) -> None:
                self.finished_task_ids: list[str] = []

            def process_task(self, task: Task) -> None:
                if task.task_id == "task-bad":
                    raise RuntimeError("boom")
                self.finished_task_ids.append(task.task_id)

        task_runner = _ExplodingOnBadTaskRunner()
        poller = _SequenceThenIdlePoller(
            [self._make_simple_task("task-bad"), self._make_simple_task("task-good")]
        )
        results: list[int] = []
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = run_worker(
                settings=Settings(
                    worker=WorkerConfig(poll_interval_seconds=0, run_once=False, max_concurrent_tasks=2),
                    platform=PlatformConfig(base_url="https://platform.example.com"),
                    nanobot=NanobotConfig(runtime_root="D:/tmp/nanobot-runtime"),
                    logging=LoggingConfig(),
                ),
                poller=poller,
                task_runner=task_runner,
                sleep=lambda _seconds: None,
                max_iterations=10,
            )

        self.assertEqual(0, exit_code)
        self.assertEqual(["task-good"], task_runner.finished_task_ids)

    def test_run_worker_applies_nanobot_timeout_environment(self) -> None:
        poller = _SequencePoller([None])
        task_runner = _FakeTaskRunner()
        output = io.StringIO()

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NANOBOT_LLM_TIMEOUT_S", None)
            os.environ.pop("NANOBOT_OPENAI_COMPAT_TIMEOUT_S", None)
            with redirect_stdout(output):
                exit_code = run_worker(
                    settings=Settings(
                        worker=WorkerConfig(poll_interval_seconds=3, run_once=True),
                        platform=PlatformConfig(base_url="https://platform.example.com"),
                        nanobot=NanobotConfig(
                            runtime_root="D:/tmp/nanobot-runtime",
                            llm_timeout_seconds=900,
                            provider_request_timeout_seconds=300,
                        ),
                        logging=LoggingConfig(),
                    ),
                    poller=poller,
                    task_runner=task_runner,
                    sleep=lambda _seconds: None,
                    max_iterations=1,
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(os.environ["NANOBOT_LLM_TIMEOUT_S"], "900")
            self.assertEqual(os.environ["NANOBOT_OPENAI_COMPAT_TIMEOUT_S"], "300")

    def test_run_worker_logs_task_source_errors_and_continues_polling(self) -> None:
        poller = _FlakyPoller()
        task_runner = _FakeTaskRunner()
        sleep_calls: list[int] = []
        output = io.StringIO()
        logger = logging.getLogger("test.worker.continue-after-task-source-error")
        logger.handlers.clear()
        logger.propagate = True

        with self.assertLogs(logger, level="WARNING") as captured_logs:
            with redirect_stdout(output):
                exit_code = run_worker(
                    settings=Settings(
                        worker=WorkerConfig(poll_interval_seconds=3, run_once=False),
                        platform=PlatformConfig(base_url="https://platform.example.com"),
                        nanobot=NanobotConfig(runtime_root="D:/tmp/nanobot-runtime"),
                        logging=LoggingConfig(),
                    ),
                    poller=poller,
                    task_runner=task_runner,
                    sleep=sleep_calls.append,
                    logger=logger,
                    max_iterations=2,
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(poller.calls, 2)
        self.assertEqual(sleep_calls, [3])
        self.assertIn("no task claimed", output.getvalue())
        self.assertIn("platform task polling unavailable", "\n".join(captured_logs.output))
        self.assertIn("502 Bad Gateway", "\n".join(captured_logs.output))

    def test_build_task_runner_uses_dispatcher_executor(self) -> None:
        task_runner = build_task_runner(
            Settings(
                worker=WorkerConfig(),
                platform=PlatformConfig(base_url="https://platform.example.com"),
                nanobot=NanobotConfig(
                    runtime_root="D:/tmp/nanobot-runtime",
                ),
                code_risk_analysis=CodeRiskAnalysisConfig(gitlab_timeout_seconds=45.0),
                logging=LoggingConfig(),
            )
        )

        dispatcher_cls = getattr(executor_module, "WorkerTaskDispatcherExecutor", None)
        self.assertIsNotNone(dispatcher_cls)
        if dispatcher_cls is None:
            return
        self.assertIsInstance(task_runner.executor, dispatcher_cls)
        self.assertIsNotNone(task_runner.executor.requirement_executor.source_downloader)
        self.assertIsNotNone(task_runner.executor.code_risk_executor)
        # gitlab_timeout_seconds 必须来自配置,而非写死的默认值。
        self.assertEqual(45.0, task_runner.executor.code_risk_executor.timeout_seconds)


if __name__ == "__main__":
    unittest.main()
