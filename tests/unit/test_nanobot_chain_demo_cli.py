import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import testing_agent_ai_worker.cli.nanobot_chain_demo as chain_demo_module
from testing_agent_ai_worker.cli.nanobot_chain_demo import main, run_chain_demo
from testing_agent_ai_worker.nanobot.runner import ChainRunResult


class _Printer:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, value: str) -> None:
        self.lines.append(value)


class NanobotChainDemoCliTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_chain_demo_reads_openapi_file_and_prints_two_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            openapi_path = Path(temp_dir) / "openapi.json"
            openapi_path.write_text('{"openapi":"3.0.0"}', encoding="utf-8")
            printer = _Printer()
            captured: dict[str, str | None] = {}

            async def fake_chain_runner(
                *,
                openapi_text: str,
                session_key: str,
                extractor_skill_name: str,
                generator_skill_name: str,
                config_path: str | None,
                workspace: str | None,
                extra_instruction: str,
            ) -> ChainRunResult:
                captured.update(
                    {
                        "openapi_text": openapi_text,
                        "session_key": session_key,
                        "extractor_skill_name": extractor_skill_name,
                        "generator_skill_name": generator_skill_name,
                        "config_path": config_path,
                        "workspace": workspace,
                        "extra_instruction": extra_instruction,
                    }
                )
                return ChainRunResult(
                    extractor_output="json result",
                    generator_output="yaml result",
                )

            exit_code = await run_chain_demo(
                openapi_json_path=str(openapi_path),
                session_key="demo:chain",
                extractor_skill_name="openapi-test-config-extractor",
                generator_skill_name="api-cases-yaml-generator",
                config_path="D:/tmp/config.json",
                workspace="D:/tmp/workspace",
                extra_instruction="帮我生成登录、项目增删改查的用例",
                runner=fake_chain_runner,
                printer=printer,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            captured,
            {
                "openapi_text": '{"openapi":"3.0.0"}',
                "session_key": "demo:chain",
                "extractor_skill_name": "openapi-test-config-extractor",
                "generator_skill_name": "api-cases-yaml-generator",
                "config_path": "D:/tmp/config.json",
                "workspace": "D:/tmp/workspace",
                "extra_instruction": "帮我生成登录、项目增删改查的用例",
            },
        )
        self.assertEqual(
            printer.lines,
            [
                "=== extractor output ===",
                "json result",
                "=== yaml generator output ===",
                "yaml result",
            ],
        )

    def test_main_uses_explicit_path_and_returns_runner_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            openapi_path = Path(temp_dir) / "openapi.json"
            openapi_path.write_text('{"openapi":"3.0.0"}', encoding="utf-8")
            original_runner = chain_demo_module.run_chain_demo
            captured: dict[str, str | None] = {}

            async def fake_run_chain_demo(**kwargs) -> int:
                captured.update(kwargs)
                return 0

            chain_demo_module.run_chain_demo = fake_run_chain_demo
            try:
                exit_code = main(
                    openapi_json_path=str(openapi_path),
                    session_key="demo:chain",
                    extractor_skill_name="openapi-test-config-extractor",
                    generator_skill_name="api-cases-yaml-generator",
                )
            finally:
                chain_demo_module.run_chain_demo = original_runner

        self.assertEqual(exit_code, 0)
        self.assertEqual(captured["openapi_json_path"], str(openapi_path))
        self.assertEqual(captured["session_key"], "demo:chain")
        self.assertEqual(captured["extractor_skill_name"], "openapi-test-config-extractor")
        self.assertEqual(captured["generator_skill_name"], "api-cases-yaml-generator")


if __name__ == "__main__":
    unittest.main()
