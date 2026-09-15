"""Guard the pinned Nanobot dependency against dropping JSON continuation prefixes."""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse
from nanobot.utils.llm_runtime import LLMRuntime

from testing_agent_ai_worker.tasks.functional_case_generate.validation import validate_output
from tests.unit.tasks.functional_case_generate.fixtures import case


class NanobotLengthRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_truncated_cases_return_complete_json_with_boundary_whitespace(self):
        expected = {"cases": [{**case(), "case_title": "Export boundary preserved"}]}
        raw = json.dumps(expected, ensure_ascii=False)
        first = raw.index("Export ") + len("Export ")
        second = raw.index("boundary ") + len("boundary ")
        parts = [raw[:first], raw[first:second], raw[second:]]
        provider = MagicMock(spec=LLMProvider)
        provider.chat_with_retry = AsyncMock(
            side_effect=[
                LLMResponse(content=part, finish_reason=reason)
                for part, reason in zip(parts, ["length", "length", "stop"])
            ]
        )
        result = await AgentRunner().run(
            AgentRunSpec(
                initial_messages=[{"role": "user", "content": "Generate cases JSON."}],
                tools=ToolRegistry(),
                runtime=LLMRuntime(
                    provider=provider,
                    model="test-model",
                    generation=GenerationSettings(),
                    context_window_tokens=200000,
                ),
                max_iterations=5,
                max_tool_result_chars=16000,
            )
        )
        self.assertEqual(result.final_content, raw)
        self.assertEqual(
            json.loads(validate_output("detailed_cases", result.final_content)), expected
        )
        self.assertEqual(provider.chat_with_retry.await_count, 3)
