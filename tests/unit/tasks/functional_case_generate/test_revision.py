import asyncio
import json
import unittest
from datetime import datetime
from types import SimpleNamespace

from testing_agent_ai_worker.config.models import NanobotConfig
from testing_agent_ai_worker.models.task import Task, TaskPayload
from testing_agent_ai_worker.tasks.functional_case_generate.detailed_batches import (
    run_functional_detailed_case_batches,
)
from testing_agent_ai_worker.tasks.functional_case_generate.executor import (
    FunctionalCaseNanobotExecutor,
)
from tests.unit.tasks.functional_case_generate.fixtures import case


class FunctionalRevisionTests(unittest.TestCase):
    def task(self, stage, checkpoint=True):
        return Task(
            claim_id="claim",
            task_id="task",
            run_id="run",
            generate_task_id="generate",
            task_type="functional_case_generate",
            project_id="project",
            sprint_id="sprint",
            requirement_id="requirement",
            checkpoint_enabled=checkpoint,
            current_stage=stage,
            config_json=json.dumps(
                {
                    "requirementAnalysis": {"purpose": "existing analysis"},
                    "caseNames": {"categories": [{"model": "login", "data": []}]},
                    "resultYaml": '{"cases":[{"case_module":"login","name":"existing case"}]}',
                    "revisionInstruction": "add error boundaries",
                }
            ),
            payload=TaskPayload(
                openapi_content="",
                source_content="original requirement",
                source_type="text",
                document_type="text",
            ),
        )

    def test_checkpoint_revision_uses_current_output_and_clears_instruction(self):
        for stage, expected in [
            ("requirement_analysis", "existing analysis"),
            ("case_names", "login"),
        ]:
            with self.subTest(stage=stage):
                calls, progress = [], []

                def skill(**kwargs):
                    calls.append(kwargs)
                    return '{"updated":true}'

                executor = FunctionalCaseNanobotExecutor(
                    nanobot_config=NanobotConfig(),
                    skill_runner=skill,
                    chain_runner=lambda **kwargs: self.fail("must not run full chain"),
                )
                result = executor.execute(
                    self.task(stage), datetime.now().astimezone(), progress.append
                )
                self.assertIsNone(result)
                self.assertIn(expected, calls[0]["input_text"])
                self.assertIn("original requirement", calls[0]["input_text"])
                self.assertIn("add error boundaries", calls[0]["input_text"])
                self.assertEqual(progress[0].stage_status, "waiting_review")
                self.assertEqual(progress[0].current_stage, stage)
                self.assertNotIn(
                    "revisionInstruction", json.loads(progress[0].intermediate_json_text)
                )

    def test_final_revision_dispatches_without_checkpoint_and_clears_instruction(self):
        for checkpoint in [False, True]:
            with self.subTest(checkpoint=checkpoint):
                calls = []

                def batches(**kwargs):
                    calls.append(kwargs)
                    return '{"cases":[{"name":"revised"}]}'

                executor = FunctionalCaseNanobotExecutor(
                    nanobot_config=NanobotConfig(),
                    detailed_batch_runner=batches,
                    chain_runner=lambda **kwargs: self.fail("must not run full chain"),
                    skill_runner=lambda **kwargs: self.fail("must not rerun upstream"),
                )
                result = executor.execute(
                    self.task("detailed_cases", checkpoint),
                    datetime.now().astimezone(),
                    lambda _: None,
                )
                self.assertIn("existing case", calls[0]["current_cases_json"])
                self.assertEqual(calls[0]["revision_instruction"], "add error boundaries")
                self.assertEqual(result.status, "success")
                self.assertNotIn("revisionInstruction", json.loads(result.intermediate_json_text))
                self.assertNotIn("resultYaml", json.loads(result.intermediate_json_text))
                self.assertIn("revised", result.output_yaml)

    def test_detailed_batches_receive_only_their_current_module(self):
        calls = []

        class Bot:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def run(self, message, **kwargs):
                calls.append(message)
                return SimpleNamespace(
                    content=json.dumps({"cases": [case(f"revised-{len(calls)}")]})
                )

        result = asyncio.run(
            run_functional_detailed_case_batches(
                requirement_analysis_json='{"purpose":"original"}',
                case_names_json=json.dumps(
                    {"categories": [{"model": "login"}, {"model": "checkout"}]}
                ),
                session_key="session",
                skill_name="generate-solution-test-cases",
                current_cases_json=json.dumps(
                    {
                        "cases": [
                            {"case_module": "login", "name": "login-existing"},
                            {"module": "checkout", "name": "checkout-existing"},
                            {"module": "manually-added", "name": "manual-existing"},
                        ]
                    }
                ),
                revision_instruction="add errors",
                from_config=lambda **kwargs: Bot(),
            )
        )
        self.assertIn("login-existing", calls[0])
        self.assertNotIn("checkout-existing", calls[0])
        self.assertIn("checkout-existing", calls[1])
        self.assertNotIn("login-existing", calls[1])
        self.assertTrue(all("add errors" in call for call in calls))
        self.assertIn("manual-existing", calls[2])
        self.assertNotIn("login-existing", calls[2])
        self.assertEqual(len(json.loads(result)["cases"]), 3)
