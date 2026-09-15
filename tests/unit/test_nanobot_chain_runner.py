import json
import sys
import unittest
from pathlib import Path

from tests.unit.tasks.functional_case_generate.fixtures import analysis, case

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import testing_agent_ai_worker.nanobot.runner as runner_module
from testing_agent_ai_worker.nanobot.runner import run_chain


class _FakeResult:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeBot:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.calls: list[dict[str, str]] = []

    async def __aenter__(self) -> "_FakeBot":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def run(self, message: str, session_key: str) -> _FakeResult:
        self.calls.append({"message": message, "session_key": session_key})
        return _FakeResult(self.outputs[len(self.calls) - 1])


class _FakeFactory:
    def __init__(self, outputs: list[str]) -> None:
        self.last_kwargs: dict[str, str | None] | None = None
        self.bot = _FakeBot(outputs)

    def __call__(self, **kwargs):
        self.last_kwargs = kwargs
        return self.bot


class NanobotChainRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_chain_uses_skill_names_and_reuses_one_session_key(self) -> None:
        factory = _FakeFactory(["step one result", "step two result"])

        result = await run_chain(
            openapi_text='{"openapi":"3.0.0"}',
            session_key="demo:chain",
            config_path="D:/tmp/config.json",
            workspace="D:/tmp/workspace",
            extractor_skill_name="openapi-test-config-extractor",
            generator_skill_name="api-cases-yaml-generator",
            extra_instruction="帮我生成登录、项目增删改查的用例",
            from_config=factory,
        )

        self.assertEqual(result.extractor_output, "step one result")
        self.assertEqual(result.generator_output, "step two result")
        self.assertEqual(
            factory.last_kwargs,
            {
                "config_path": "D:/tmp/config.json",
                "workspace": "D:/tmp/workspace",
            },
        )
        self.assertEqual(
            [call["session_key"] for call in factory.bot.calls],
            ["demo:chain", "demo:chain"],
        )
        self.assertIn(
            "请先加载本地 skill：openapi-test-config-extractor", factory.bot.calls[0]["message"]
        )
        self.assertIn('{"openapi":"3.0.0"}', factory.bot.calls[0]["message"])
        self.assertIn("帮我生成登录、项目增删改查的用例", factory.bot.calls[0]["message"])
        self.assertIn(
            "符合 openapi-test-config-extractor skill 要求的接口配置 JSON",
            factory.bot.calls[0]["message"],
        )
        self.assertIn(
            "不要返回测试用例、meta/config/testCases 结构", factory.bot.calls[0]["message"]
        )
        self.assertIn(
            "请先加载本地 skill：api-cases-yaml-generator", factory.bot.calls[1]["message"]
        )
        self.assertIn("step one result", factory.bot.calls[1]["message"])
        self.assertIn("帮我生成登录、项目增删改查的用例", factory.bot.calls[1]["message"])
        self.assertIn(
            "符合 api-cases-yaml-generator skill 要求的 YAML 内容", factory.bot.calls[1]["message"]
        )
        self.assertIn("不要返回 JSON、meta/config/testCases 结构", factory.bot.calls[1]["message"])
        self.assertNotIn("请直接返回 JSON 内容", factory.bot.calls[1]["message"])

    async def test_run_functional_chain_uses_three_skill_names_and_reuses_one_session_key(
        self,
    ) -> None:
        run_functional_chain = getattr(runner_module, "run_functional_chain", None)
        self.assertIsNotNone(run_functional_chain)
        if run_functional_chain is None:
            return

        case_names_json = (
            '{"categories":['
            '{"model":"登录","data":[{"test_model":"功能场景","test_points":[{"case_name":"验证登录成功"}]}]},'
            '{"model":"项目管理","data":[{"test_model":"功能场景","test_points":[{"case_name":"验证项目新增成功"}]}]}'
            "]}"
        )
        factory = _FakeFactory(
            [
                json.dumps(analysis(), ensure_ascii=False, separators=(",", ":")),
                case_names_json,
                json.dumps({"cases": [case("验证登录成功")]}),
                json.dumps({"cases": [case("验证项目新增成功", "项目管理")]}),
            ]
        )
        stage_outputs: list[str] = []
        batch_progress: list[tuple[str, str, int, int]] = []

        result = await run_functional_chain(
            source_text="请基于登录和项目管理需求生成功能测试用例",
            session_key="demo:functional",
            config_path="D:/tmp/config.json",
            workspace="D:/tmp/workspace",
            analysis_skill_name="analyze-functional-requirements",
            case_name_skill_name="generate-solution-test-points",
            detailed_case_skill_name="generate-solution-test-cases",
            extra_instruction="只保留核心业务场景",
            on_requirement_analysis_result=stage_outputs.append,
            on_case_names_result=stage_outputs.append,
            on_detailed_cases_progress=lambda accumulated_result, model_name, index, total: (
                batch_progress.append((accumulated_result, model_name, index, total))
            ),
            from_config=factory,
        )

        self.assertEqual(
            result.requirement_analysis_output,
            json.dumps(analysis(), ensure_ascii=False, separators=(",", ":")),
        )
        self.assertEqual(json.loads(result.case_names_output), json.loads(case_names_json))
        self.assertEqual(
            json.loads(result.detailed_cases_output),
            {"cases": [case("验证登录成功"), case("验证项目新增成功", "项目管理")]},
        )
        self.assertEqual(
            [json.loads(value) for value in stage_outputs],
            [analysis(), json.loads(case_names_json)],
        )
        self.assertEqual(len(batch_progress), 2)
        self.assertEqual(batch_progress[0][1:], ("登录", 1, 2))
        self.assertEqual(batch_progress[1][1:], ("项目管理", 2, 2))
        self.assertEqual(
            [call["session_key"] for call in factory.bot.calls],
            ["demo:functional", "demo:functional", "demo:functional", "demo:functional"],
        )
        self.assertIn(
            "请先加载本地 skill：analyze-functional-requirements", factory.bot.calls[0]["message"]
        )
        self.assertIn("请基于登录和项目管理需求生成功能测试用例", factory.bot.calls[0]["message"])
        self.assertIn(
            "请先加载本地 skill：generate-solution-test-points", factory.bot.calls[1]["message"]
        )
        self.assertIn(
            json.dumps(analysis(), ensure_ascii=False, separators=(",", ":")),
            factory.bot.calls[1]["message"],
        )
        self.assertIn(
            "请先加载本地 skill：generate-solution-test-cases", factory.bot.calls[2]["message"]
        )
        self.assertIn(
            json.dumps(analysis(), ensure_ascii=False, separators=(",", ":")),
            factory.bot.calls[2]["message"],
        )
        self.assertIn('"model": "登录"', factory.bot.calls[2]["message"])
        self.assertIn(
            "请直接返回包含 cases 数组的详细测试用例 JSON", factory.bot.calls[2]["message"]
        )
        self.assertIn(
            "请先加载本地 skill：generate-solution-test-cases", factory.bot.calls[3]["message"]
        )
        self.assertIn('"model": "项目管理"', factory.bot.calls[3]["message"])
        self.assertIn(
            "请直接返回包含 cases 数组的详细测试用例 JSON", factory.bot.calls[3]["message"]
        )
        self.assertIn("只保留核心业务场景", factory.bot.calls[3]["message"])

    async def test_run_requirement_analysis_chain_uses_three_skill_names_without_api_constraints(
        self,
    ) -> None:
        run_requirement_analysis_chain = getattr(
            runner_module, "run_requirement_analysis_chain", None
        )
        self.assertIsNotNone(run_requirement_analysis_chain)
        if run_requirement_analysis_chain is None:
            return

        factory = _FakeFactory(
            ["normalized requirement", "first analysis", "analysis:\n  summary: done"]
        )
        stage_outputs: list[str] = []

        result = await run_requirement_analysis_chain(
            source_text="需求正文内容",
            session_key="demo:requirement-analysis",
            config_path="D:/tmp/config.json",
            workspace="D:/tmp/workspace",
            first_skill_name="requirement-step-zero",
            second_skill_name="requirement-step-one",
            third_skill_name="requirement-step-two",
            extra_instruction="重点分析异常场景和歧义点",
            on_first_step_result=stage_outputs.append,
            on_second_step_result=stage_outputs.append,
            from_config=factory,
        )

        self.assertEqual(result.first_step_output, "normalized requirement")
        self.assertEqual(result.second_step_output, "first analysis")
        self.assertEqual(result.final_output, "analysis:\n  summary: done")
        self.assertEqual(stage_outputs, ["normalized requirement", "first analysis"])
        self.assertEqual(
            [call["session_key"] for call in factory.bot.calls],
            ["demo:requirement-analysis", "demo:requirement-analysis", "demo:requirement-analysis"],
        )
        self.assertIn("请先加载本地 skill：requirement-step-zero", factory.bot.calls[0]["message"])
        self.assertIn("需求正文内容", factory.bot.calls[0]["message"])
        self.assertIn("重点分析异常场景和歧义点", factory.bot.calls[0]["message"])
        self.assertIn("请先加载本地 skill：requirement-step-one", factory.bot.calls[1]["message"])
        self.assertIn("normalized requirement", factory.bot.calls[1]["message"])
        self.assertIn("重点分析异常场景和歧义点", factory.bot.calls[1]["message"])
        self.assertIn("请先加载本地 skill：requirement-step-two", factory.bot.calls[2]["message"])
        self.assertIn("first analysis", factory.bot.calls[2]["message"])
        self.assertIn("重点分析异常场景和歧义点", factory.bot.calls[2]["message"])
        self.assertNotIn("符合 openapi-test-config-extractor", factory.bot.calls[0]["message"])
        self.assertNotIn("符合 api-cases-yaml-generator", factory.bot.calls[2]["message"])


if __name__ == "__main__":
    unittest.main()
