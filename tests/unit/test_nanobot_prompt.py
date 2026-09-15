import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from testing_agent_ai_worker.nanobot_runtime.prompt import (
    FUNCTIONAL_ANALYSIS_JSON_ONLY_INSTRUCTION,
    FUNCTIONAL_DETAILED_CASES_JSON_ONLY_INSTRUCTION,
    append_stage_instruction,
    build_skill_message,
)


class NanobotPromptTests(unittest.TestCase):
    def test_append_stage_instruction_appends_to_extra_instruction_like_api_chain(self) -> None:
        self.assertEqual(
            append_stage_instruction(" 优先覆盖核心链路 ", "只返回 JSON"),
            "优先覆盖核心链路\n\n只返回 JSON",
        )

    def test_append_stage_instruction_returns_stage_instruction_when_extra_is_blank(self) -> None:
        self.assertEqual(append_stage_instruction("  ", "只返回 JSON"), "只返回 JSON")

    def test_build_skill_message_asks_nanobot_to_load_local_skill_first(self) -> None:
        self.assertEqual(
            build_skill_message(
                skill_name="analyze-functional-requirements",
                body_text="需求正文",
                extra_instruction="只返回 JSON",
            ),
            "\n\n".join(
                [
                    "请先加载本地 skill：analyze-functional-requirements，并严格遵循该 SKILL.md 的全部规则。",
                    "需求正文",
                    "只返回 JSON",
                ]
            ),
        )

    def test_functional_analysis_instruction_requires_exactly_one_json_object(self) -> None:
        self.assertIn("且只能是一个", FUNCTIONAL_ANALYSIS_JSON_ONLY_INSTRUCTION)
        self.assertIn("JSON.parse", FUNCTIONAL_ANALYSIS_JSON_ONLY_INSTRUCTION)
        self.assertIn("第二个 JSON 对象", FUNCTIONAL_ANALYSIS_JSON_ONLY_INSTRUCTION)

    def test_functional_detailed_cases_instruction_requires_single_cases_json_object(self) -> None:
        self.assertIn("cases 数组", FUNCTIONAL_DETAILED_CASES_JSON_ONLY_INSTRUCTION)
        self.assertIn("且只能是一个", FUNCTIONAL_DETAILED_CASES_JSON_ONLY_INSTRUCTION)
        self.assertIn("第二个 JSON 对象", FUNCTIONAL_DETAILED_CASES_JSON_ONLY_INSTRUCTION)


if __name__ == "__main__":
    unittest.main()
