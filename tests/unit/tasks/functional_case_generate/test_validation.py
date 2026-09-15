import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from testing_agent_ai_worker.tasks.functional_case_generate.chain import (
    run_functional_chain,
)
from testing_agent_ai_worker.tasks.functional_case_generate.detailed_batches import (
    run_functional_detailed_case_batches,
)
from testing_agent_ai_worker.tasks.functional_case_generate.validation import (
    OutputValidationError,
    ValidationContext,
    context,
    generate_validated,
    validate_output,
)
from tests.unit.tasks.functional_case_generate.fixtures import analysis, case, points


class ContractsTests(unittest.TestCase):
    def test_all_three_valid_and_required_nullable(self):
        for stage, output in [
            ("requirement_analysis", analysis()),
            ("case_names", points()),
            ("detailed_cases", {"cases": [case()]}),
        ]:
            self.assertEqual(json.loads(validate_output(stage, json.dumps(output))), output)
        data = analysis()
        del data["functionalOverview"]["purpose"]
        with self.assertRaises(ValueError):
            validate_output("requirement_analysis", json.dumps(data))

    def test_strict_json(self):
        for text in [
            '{"cases":',
            '{"cases":[],"cases":[]}',
            '{"cases":NaN}',
            '{"cases":Infinity}',
            'before {"cases":[]}',
            '```json\n{"cases":[]}',
        ]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                validate_output("detailed_cases", text)
        self.assertEqual(
            validate_output("detailed_cases", ' ```json\n{"cases":[]}\n``` '),
            '{"cases":[]}',
        )

    def test_case_fields_and_relationships(self):
        for changes in [
            {"priority": 2},
            {"priority": "P0"},
            {"extra": True},
            {"case_title": " "},
            {"case_type": "wrong"},
            {"test_steps": []},
            {"expected_results": ["2. bad numbering"]},
            {"test_steps": ["1. a", "2. b"]},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_output("detailed_cases", json.dumps({"cases": [{**case(), **changes}]}))
        with self.assertRaises(ValueError):
            validate_output("detailed_cases", json.dumps({"cases": [case(), case()]}))

    def test_ids_and_references(self):
        data = analysis()
        q = {
            "questionId": "Q01",
            "question": "何时生效？",
            "affectedScope": None,
            "blockedWork": None,
        }
        data["openQuestions"] = [q, q]
        with self.assertRaises(ValueError):
            validate_output("requirement_analysis", json.dumps(data))
        data["openQuestions"] = []
        data["scenarioBreakdown"] = [
            {
                "scenarioId": "S01",
                "relatedRuleIds": ["R99"],
                "derivationType": "需求直接描述",
                "conditions": [],
                "trigger": None,
                "verificationObjective": "检查入口",
                "readyForTestPointGeneration": True,
                "blockingReason": None,
                "relatedQuestionIds": [],
            }
        ]
        with self.assertRaisesRegex(ValueError, "relatedRuleIds"):
            validate_output("requirement_analysis", json.dumps(data))


class RepairTests(unittest.IsolatedAsyncioTestCase):
    async def test_repairs_each_stage_and_records_full_diagnostics(self):
        for stage, valid in [
            ("requirement_analysis", analysis()),
            ("case_names", points()),
            ("detailed_cases", {"cases": [case()]}),
        ]:
            calls, events = [], []

            async def generate(prompt):
                calls.append(prompt)
                return '{"broken":' if len(calls) == 1 else json.dumps(valid)

            with tempfile.TemporaryDirectory() as tmp:
                token = context.set(ValidationContext(Path(tmp), events.append))
                try:
                    output = await generate_validated(
                        stage=stage, inputs="原始输入及本轮优化要求", generate=generate
                    )
                finally:
                    context.reset(token)
                self.assertEqual(json.loads(output), valid)
                self.assertEqual(len(calls), 2)
                self.assertIn('"path": "$"', calls[1])
                self.assertIn("原始输入及本轮优化要求", calls[1])
                self.assertEqual(events[-1]["repairAttempt"], 1)
                self.assertEqual(len(list(Path(tmp).rglob("attempt-*.json"))), 2)

    async def test_limit_transport_and_truncation(self):
        for kind, count in [("format", 3), ("network", 1), ("length", 1)]:
            calls = []

            async def generate(prompt):
                calls.append(prompt)
                if kind == "network":
                    raise ConnectionError("unavailable")
                return SimpleNamespace(
                    content="broken",
                    finish_reason="length" if kind == "length" else None,
                )

            with self.assertRaises((OutputValidationError, ConnectionError)):
                await generate_validated(stage="case_names", inputs="input", generate=generate)
            self.assertEqual(len(calls), count)

    async def test_error_feedback_caps_and_specific_path(self):
        calls = []
        bad = {"cases": [{**case(), "priority": 2, "case_title": "x" * 500}] * 30}

        async def generate(prompt):
            calls.append(prompt)
            return json.dumps(bad if len(calls) == 1 else {"cases": [case()]})

        await generate_validated(stage="detailed_cases", inputs="input", generate=generate)
        feedback = calls[1].split("【校验问题，最多列出20项】\n")[1].split("\n请保留")[0]
        errors = json.loads(feedback)
        self.assertEqual(len(errors), 20)
        self.assertEqual(errors[0]["path"], "$.cases[0].priority")
        self.assertTrue(all(len(e["actual"]) <= 200 for e in errors))

    async def test_batch_duplicate_repairs_later_batch_no_partial_publish(self):
        calls, progress = [], []

        class Bot:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def run(self, prompt, **kwargs):
                calls.append(prompt)
                return json.dumps({"cases": [case("first" if len(calls) < 3 else "second")]})

        result = await run_functional_detailed_case_batches(
            requirement_analysis_json="{}",
            case_names_json=json.dumps({"categories": [{"model": "A"}, {"model": "B"}]}),
            session_key="test",
            skill_name="generate-solution-test-cases",
            from_config=lambda **kw: Bot(),
            on_progress=lambda *args: progress.append(args),
        )
        self.assertEqual(len(calls), 3)
        self.assertIn("duplicate", calls[2])
        self.assertEqual(len(json.loads(result)["cases"]), 2)
        self.assertTrue(all(p[0] == "" for p in progress))

    async def test_full_chain_validates_before_stage_callback(self):
        calls, outputs = [], []
        responses = [
            "bad",
            json.dumps(analysis()),
            json.dumps(points()),
            json.dumps({"cases": [case()]}),
        ]

        class Bot:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def run(self, prompt, **kwargs):
                calls.append(prompt)
                return responses.pop(0)

        result = await run_functional_chain(
            source_text="原始需求",
            session_key="test",
            analysis_skill_name="analyze-functional-requirements",
            case_name_skill_name="generate-solution-test-points",
            detailed_case_skill_name="generate-solution-test-cases",
            from_config=lambda **kw: Bot(),
            on_requirement_analysis_result=outputs.append,
            on_case_names_result=outputs.append,
        )
        self.assertEqual(len(calls), 4)
        self.assertEqual(len(outputs), 2)
        self.assertEqual(json.loads(outputs[0]), analysis())
        self.assertEqual(len(json.loads(result.detailed_cases_output)["cases"]), 1)

    async def test_noncheckpoint_resume_skips_confirmed_upstream(self):
        calls, outputs = [], []

        class Bot:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def run(self, prompt, **kwargs):
                calls.append(prompt)
                return json.dumps({"cases": [case()]})

        result = await run_functional_chain(
            source_text="需求",
            session_key="retry",
            analysis_skill_name="analyze-functional-requirements",
            case_name_skill_name="generate-solution-test-points",
            detailed_case_skill_name="generate-solution-test-cases",
            from_config=lambda **kw: Bot(),
            resume_stage="detailed_cases",
            prior_analysis=json.dumps(analysis()),
            prior_case_names=json.dumps(points()),
            on_requirement_analysis_result=outputs.append,
            on_case_names_result=outputs.append,
        )
        self.assertEqual(len(calls), 1)
        self.assertFalse(outputs)
        self.assertEqual(len(json.loads(result.detailed_cases_output)["cases"]), 1)

    async def test_sdk_errors_do_not_trigger_repairs(self):
        calls = []

        async def generate(prompt):
            calls.append(prompt)
            return SimpleNamespace(content="auth failed", error="auth failed")

        with self.assertRaisesRegex(RuntimeError, "模型调用失败"):
            await generate_validated(stage="case_names", inputs="input", generate=generate)
        self.assertEqual(len(calls), 1)


class CheckpointValidationTests(unittest.TestCase):
    def test_checkpoint_and_revision_validate_before_waiting_review(self):
        from datetime import datetime
        from unittest.mock import patch

        from testing_agent_ai_worker.config.models import NanobotConfig
        from testing_agent_ai_worker.models.task import Task, TaskPayload
        from testing_agent_ai_worker.tasks.functional_case_generate.executor import (
            FunctionalCaseNanobotExecutor,
        )

        for stage, valid, field in [
            ("requirement_analysis", analysis(), "requirementAnalysis"),
            ("case_names", points(), "caseNames"),
        ]:
            calls, progress = [], []

            class Bot:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    pass

                async def run(self, prompt, **kwargs):
                    calls.append(prompt)
                    return SimpleNamespace(
                        content="invalid" if len(calls) == 1 else json.dumps(valid)
                    )

            with (
                tempfile.TemporaryDirectory() as tmp,
                patch(
                    "testing_agent_ai_worker.tasks.functional_case_generate.chain._default_from_config",
                    return_value=Bot(),
                ),
            ):
                task = Task(
                    claim_id="c",
                    task_id="t",
                    run_id="r",
                    generate_task_id="g",
                    task_type="functional_case_generate",
                    project_id="p",
                    sprint_id="s",
                    requirement_id="req",
                    checkpoint_enabled=True,
                    current_stage=stage,
                    config_json=json.dumps(
                        {
                            "requirementAnalysis": analysis(),
                            "caseNames": points(),
                            "revisionInstruction": "补充异常",
                        }
                    ),
                    payload=TaskPayload(
                        source_type="text",
                        document_type="text",
                        source_content="需求",
                        openapi_content="",
                    ),
                )
                result = FunctionalCaseNanobotExecutor(
                    nanobot_config=NanobotConfig(runtime_root=tmp)
                ).execute(task, datetime.now().astimezone(), progress.append)
                self.assertIsNone(result)
                self.assertEqual(len(calls), 2)
                self.assertIn("补充异常", calls[1])
                self.assertEqual(progress[-1].stage_status, "waiting_review")
                self.assertEqual(json.loads(progress[-1].intermediate_json_text)[field], valid)
                self.assertTrue(all(not p.intermediate_json_text for p in progress[:-1]))
                self.assertNotIn("revisionInstruction", progress[-1].intermediate_json_text)
