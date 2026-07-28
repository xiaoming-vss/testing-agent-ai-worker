import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from testing_agent_ai_worker.config.models import NanobotConfig
from testing_agent_ai_worker.models.task import LlmCredentials, Task, TaskPayload
import testing_agent_ai_worker.nanobot.config_builder as config_builder_module
from testing_agent_ai_worker.nanobot.config_builder import task_config_path


class NanobotConfigBuilderTests(unittest.TestCase):
    def _make_task(self, *, with_credentials: bool = True) -> Task:
        return Task(
            task_id="task-1",
            run_id="run-1",
            generate_task_id="generate-1",
            task_type="api_case_generate",
            payload=TaskPayload(
                openapi_content='{"openapi":"3.0.0"}',
                llm_credentials=(
                    LlmCredentials(
                        model="gpt-5.4-mini",
                        api_key="platform-key",
                        base_url="https://example.test/v1",
                    )
                    if with_credentials
                    else None
                ),
            ),
        )

    def test_task_config_path_overlays_platform_llm_credentials_into_temp_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            template_path = Path(temp_dir) / "nanobot.template.json"
            template_path.write_text(
                json.dumps(
                    {
                        "agents": {
                            "defaults": {
                                "provider": "auto",
                                "model": "gpt-4.1",
                                "temperature": 0.2,
                            }
                        },
                        "providers": {
                            "custom": {
                                "apiKey": None,
                                "apiBase": None,
                                "apiType": "auto",
                            }
                        },
                        "tools": {"enabled": True},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            runtime_root = Path(temp_dir) / "runtime-root"
            nanobot_config = NanobotConfig(runtime_root=str(runtime_root))

            with patch.object(config_builder_module, "DEFAULT_TEMPLATE_PATH", template_path):
                with task_config_path(
                    nanobot_config=nanobot_config,
                    task=self._make_task(),
                ) as resolved_path:
                    self.assertIsNotNone(resolved_path)
                    self.assertNotEqual(resolved_path, str(template_path))
                    self.assertEqual(Path(resolved_path).parent, runtime_root / "temp-configs")

                    generated_config = json.loads(Path(resolved_path).read_text(encoding="utf-8"))
                    self.assertEqual(generated_config["agents"]["defaults"]["provider"], "auto")
                    self.assertEqual(generated_config["agents"]["defaults"]["model"], "gpt-5.4-mini")
                    self.assertEqual(generated_config["providers"]["custom"]["apiKey"], "platform-key")
                    self.assertEqual(
                        generated_config["providers"]["custom"]["apiBase"],
                        "https://example.test/v1",
                    )
                    self.assertEqual(generated_config["tools"], {"enabled": True})

                self.assertFalse(Path(resolved_path).exists())

    def test_task_config_path_returns_template_path_when_task_has_no_llm_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            template_path = Path(temp_dir) / "nanobot.template.json"
            template_path.write_text("{}", encoding="utf-8")
            nanobot_config = NanobotConfig(runtime_root=str(Path(temp_dir) / "runtime-root"))

            with patch.object(config_builder_module, "DEFAULT_TEMPLATE_PATH", template_path):
                with task_config_path(
                    nanobot_config=nanobot_config,
                    task=self._make_task(with_credentials=False),
                ) as resolved_path:
                    self.assertEqual(resolved_path, str(template_path))


if __name__ == "__main__":
    unittest.main()
