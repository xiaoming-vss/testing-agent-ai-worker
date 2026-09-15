import asyncio
import json
import sys
import unittest
from pathlib import Path

from tests.unit.tasks.functional_case_generate.fixtures import analysis

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from testing_agent_ai_worker.nanobot_runtime.prompt import (
    FUNCTIONAL_ANALYSIS_JSON_ONLY_INSTRUCTION,
    FUNCTIONAL_CASE_NAMES_JSON_ONLY_INSTRUCTION,
    FUNCTIONAL_DETAILED_CASES_JSON_ONLY_INSTRUCTION,
)
from testing_agent_ai_worker.tasks.functional_case_generate.chain import (
    run_functional_chain,
    run_skill_step,
)


class _FakeResult:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeBot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def run(self, message: str, *, session_key: str):
        self.calls.append((message, session_key))
        call_index = len(self.calls)
        if call_index == 1:
            return _FakeResult(json.dumps(analysis(), ensure_ascii=False))
        if call_index == 2:
            return _FakeResult(
                json.dumps(
                    {
                        "categories": [
                            {
                                "model": "登录",
                                "data": [
                                    {
                                        "test_model": "功能场景",
                                        "test_points": [{"case_name": "验证登录成功"}],
                                    }
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
            )
        return _FakeResult(json.dumps({"cases": []}, ensure_ascii=False))


class FunctionalChainPromptTests(unittest.TestCase):
    def test_run_functional_chain_appends_stage_specific_json_only_instructions(self) -> None:
        bot = _FakeBot()

        def fake_from_config(**kwargs):
            return bot

        result = asyncio.run(
            run_functional_chain(
                source_text="登录后可以查看项目",
                session_key="task:1",
                analysis_skill_name="analyze-functional-requirements",
                case_name_skill_name="generate-solution-test-points",
                detailed_case_skill_name="generate-solution-test-cases",
                extra_instruction="优先覆盖核心业务链路",
                from_config=fake_from_config,
            )
        )

        self.assertEqual(result.detailed_cases_output, '{"cases": []}')
        self.assertEqual(len(bot.calls), 3)
        analysis_message = bot.calls[0][0]
        case_names_message = bot.calls[1][0]
        detailed_cases_message = bot.calls[2][0]
        self.assertIn("请先加载本地 skill：analyze-functional-requirements", analysis_message)
        self.assertIn("优先覆盖核心业务链路", analysis_message)
        self.assertIn(FUNCTIONAL_ANALYSIS_JSON_ONLY_INSTRUCTION, analysis_message)
        self.assertIn("请先加载本地 skill：generate-solution-test-points", case_names_message)
        self.assertIn(FUNCTIONAL_CASE_NAMES_JSON_ONLY_INSTRUCTION, case_names_message)
        self.assertIn("登录后可以查看项目", case_names_message)
        self.assertIn("functionalOverview", case_names_message)
        self.assertIn("请先加载本地 skill：generate-solution-test-cases", detailed_cases_message)
        self.assertIn(FUNCTIONAL_DETAILED_CASES_JSON_ONLY_INSTRUCTION, detailed_cases_message)
        self.assertIn("登录后可以查看项目", detailed_cases_message)

    def test_run_skill_step_appends_instruction_by_functional_skill_name(self) -> None:
        bot = _FakeBot()

        def fake_from_config(**kwargs):
            return bot

        asyncio.run(
            run_skill_step(
                input_text="登录需求",
                session_key="task:1",
                skill_name="analyze-functional-requirements",
                extra_instruction="只看功能路径",
                from_config=fake_from_config,
            )
        )

        self.assertEqual(len(bot.calls), 1)
        message = bot.calls[0][0]
        self.assertIn("只看功能路径", message)
        self.assertIn(FUNCTIONAL_ANALYSIS_JSON_ONLY_INSTRUCTION, message)


if __name__ == "__main__":
    unittest.main()
