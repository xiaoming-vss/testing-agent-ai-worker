import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from testing_agent_ai_worker.config.models import NanobotConfig
from testing_agent_ai_worker.models.execution import TaskProgress, TaskStatus
from testing_agent_ai_worker.models.task import LlmCredentials, Task, TaskPayload
from testing_agent_ai_worker.tasks.api_case_generate.chain import ChainRunResult
from testing_agent_ai_worker.tasks.api_case_generate.executor import ApiCaseNanobotExecutor


class ApiCaseExecutorTests(unittest.TestCase):
    def _make_task(self, *, task_type: str = "api_case_generate") -> Task:
        return Task(
            claim_id="claim-api-1",
            task_id="task-1",
            run_id="run-1",
            generate_task_id="generate-1",
            task_type=task_type,
            project_id="project-1",
            sprint_id="sprint-1",
            requirement_id="requirement-1",
            payload=TaskPayload(
                openapi_content='{"openapi":"3.0.0"}',
                source_content='{"openapi":"3.0.0"}',
                source_type="openapi",
                target_scope="只处理登录与鉴权接口",
                extra_instruction="帮我生成登录、项目增删改查的用例",
            ),
        )

    def test_execute_runs_chain_submits_progress_and_returns_success_result(self) -> None:
        task = self._make_task()
        progress_events: list[TaskProgress] = []
        captured: dict[str, object] = {}
        events: list[str] = []

        def fake_chain_runner(
            **kwargs,
        ) -> ChainRunResult:
            events.append("chain")
            captured.update(kwargs)
            callback = kwargs["on_extractor_result"]
            callback("json result")
            return ChainRunResult(
                extractor_output="json result",
                generator_output="cases:\n  - name: login",
            )

        executor = ApiCaseNanobotExecutor(
            nanobot_config=NanobotConfig(
                runtime_root="D:/tmp/nanobot-runtime",
            ),
            chain_runner=fake_chain_runner,
        )

        result = executor.execute(
            task,
            datetime.fromisoformat("2026-06-23T10:00:00+08:00"),
            progress_events.append,
        )

        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertEqual(result.intermediate_json_text, "json result")
        self.assertEqual(result.output_yaml, "cases:\n  - name: login")
        self.assertEqual(len(progress_events), 1)
        self.assertEqual(progress_events[0].task_id, "task-1")
        self.assertEqual(progress_events[0].intermediate_json_text, "json result")
        self.assertEqual(progress_events[0].current_stage, "openapi_extract")
        self.assertEqual(progress_events[0].stage_status, "running")
        self.assertEqual(captured["session_key"], "run-1")
        self.assertEqual(
            Path(str(captured["workspace"])),
            Path("D:/tmp/nanobot-runtime/workspaces/project-project-1"),
        )
        self.assertEqual(events, ["chain"])
        self.assertTrue(str(captured["config_path"]).endswith("nanobot.template.json"))
        self.assertEqual(captured["extractor_skill_name"], "openapi-test-config-extractor")
        self.assertEqual(captured["generator_skill_name"], "api-cases-yaml-generator")
        self.assertIn("只处理登录与鉴权接口", captured["extra_instruction"])
        self.assertIn("帮我生成登录、项目增删改查的用例", captured["extra_instruction"])

        summary = json.loads(result.result_summary_json)
        self.assertEqual(summary["status"], "success")
        self.assertEqual(summary["taskType"], "api_case_generate")

    def test_execute_returns_failed_result_for_unsupported_task_type(self) -> None:
        task = self._make_task(task_type="functional_case_generate")
        executor = ApiCaseNanobotExecutor(
            nanobot_config=NanobotConfig(),
            chain_runner=lambda **kwargs: ChainRunResult("", ""),
        )

        result = executor.execute(
            task,
            datetime.fromisoformat("2026-06-23T10:00:00+08:00"),
            lambda progress: None,
        )

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("functional_case_generate", result.error_message or "")

    def test_execute_uses_task_scoped_nanobot_config_when_llm_credentials_exist(self) -> None:
        task = self._make_task()
        task.payload.llm_credentials = LlmCredentials(
            model="gpt-5.4-mini",
            api_key="platform-key",
            base_url="https://example.test/v1",
        )
        captured: dict[str, object] = {}

        with tempfile.TemporaryDirectory() as temp_dir:
            base_config_path = Path(temp_dir) / "nanobot.json"
            base_config_path.write_text(
                json.dumps(
                    {
                        "agents": {"defaults": {"provider": "auto", "model": "gpt-4.1"}},
                        "providers": {"custom": {"apiKey": None, "apiBase": None}},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            def fake_chain_runner(**kwargs) -> ChainRunResult:
                captured.update(kwargs)
                generated_config = json.loads(
                    Path(str(kwargs["config_path"])).read_text(encoding="utf-8")
                )
                self.assertEqual(generated_config["agents"]["defaults"]["provider"], "auto")
                self.assertEqual(generated_config["agents"]["defaults"]["model"], "gpt-5.4-mini")
                self.assertEqual(generated_config["providers"]["custom"]["apiKey"], "platform-key")
                self.assertEqual(
                    generated_config["providers"]["custom"]["apiBase"],
                    "https://example.test/v1",
                )
                return ChainRunResult(
                    extractor_output="json result",
                    generator_output="cases:\n  - name: login",
                )

            executor = ApiCaseNanobotExecutor(
                nanobot_config=NanobotConfig(
                    runtime_root=str(Path(temp_dir) / "runtime-root"),
                ),
                chain_runner=fake_chain_runner,
            )

            result = executor.execute(
                task,
                datetime.fromisoformat("2026-06-23T10:00:00+08:00"),
                lambda progress: None,
            )

        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertNotEqual(captured["config_path"], str(base_config_path))


if __name__ == "__main__":
    unittest.main()
