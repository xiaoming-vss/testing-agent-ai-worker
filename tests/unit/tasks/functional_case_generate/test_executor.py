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

import testing_agent_ai_worker.tasks.functional_case_generate.executor as executor_module
from testing_agent_ai_worker.nanobot_runtime.prompt import (
    FUNCTIONAL_ANALYSIS_JSON_ONLY_INSTRUCTION,
    FUNCTIONAL_CASE_NAMES_JSON_ONLY_INSTRUCTION,
)
from testing_agent_ai_worker.tasks.functional_case_generate.chain import FunctionalChainRunResult
from testing_agent_ai_worker.config.models import NanobotConfig
from testing_agent_ai_worker.models.execution import TaskProgress, TaskStatus
from testing_agent_ai_worker.models.task import LlmCredentials, Task, TaskPayload


class FunctionalCaseExecutorTests(unittest.TestCase):
    def _make_task(
        self,
        *,
        source_type: str = "text",
        document_type: str = "text",
        checkpoint_enabled: bool = False,
        current_stage: str = "",
        config_json: str = "",
    ) -> Task:
        return Task(
            claim_id="claim-functional-1",
            task_id="task-functional-1",
            run_id="run-functional-1",
            generate_task_id="generate-functional-1",
            task_type="functional_case_generate",
            project_id="project-1",
            sprint_id="sprint-1",
            requirement_id="requirement-1",
            checkpoint_enabled=checkpoint_enabled,
            current_stage=current_stage,
            config_json=config_json,
            payload=TaskPayload(
                openapi_content="",
                source_content="登录后可以新增、编辑、删除项目，并查看项目详情",
                source_type=source_type,
                document_type=document_type,
                extra_instruction="优先覆盖核心业务链路和异常场景",
            ),
        )

    def test_execute_runs_three_step_chain_submits_two_progress_events_and_returns_success(self) -> None:
        executor_cls = getattr(executor_module, "FunctionalCaseNanobotExecutor", None)
        chain_result_cls = getattr(executor_module, "FunctionalChainRunResult", None)
        self.assertIsNotNone(executor_cls)
        self.assertIsNotNone(chain_result_cls)
        if executor_cls is None or chain_result_cls is None:
            return

        task = self._make_task()
        progress_events: list[TaskProgress] = []
        captured: dict[str, object] = {}
        events: list[str] = []

        class FakeSkillSyncer:
            def sync_project_skills(self, *, project_id: str, workspace: Path) -> None:
                events.append("sync")
                self.project_id = project_id
                self.workspace = workspace

        requirement_analysis_json = json.dumps(
            {
                "Platform_core_functions": ["登录", "项目管理"],
                "Target_understanding": ["覆盖核心业务"],
                "Risk_point_prediction": ["权限错误"],
                "function_flow": ["登录", "进入项目列表", "新增项目"],
                "Scene_Design": [{"scene_type": "功能场景"}],
            },
            ensure_ascii=False,
        )
        case_names_json = json.dumps(
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
                    },
                    {
                        "model": "项目管理",
                        "data": [
                            {
                                "test_model": "功能场景",
                                "test_points": [{"case_name": "验证项目新增成功"}],
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        )
        detailed_cases_json = json.dumps(
            {
                "cases": [
                    {
                        "case_module": "登录",
                        "case_title": "验证登录成功",
                        "case_type": "功能测试",
                        "priority": "1",
                        "precondition": ["1. 用户已进入登录页"],
                        "test_steps": ["1. 输入正确账号密码并登录"],
                        "expected_results": ["1. 登录成功并跳转到首页"],
                    },
                    {
                        "case_module": "项目管理",
                        "case_title": "验证项目新增成功",
                        "case_type": "功能测试",
                        "priority": "1",
                        "precondition": ["1. 用户已成功登录"],
                        "test_steps": ["1. 新增项目并提交"],
                        "expected_results": ["1. 项目新增成功并展示在列表中"],
                    }
                ]
            },
            ensure_ascii=False,
        )
        detailed_cases_after_first_batch = json.dumps(
            {
                "cases": [
                    {
                        "case_module": "登录",
                        "case_title": "验证登录成功",
                        "case_type": "功能测试",
                        "priority": "1",
                        "precondition": ["1. 用户已进入登录页"],
                        "test_steps": ["1. 输入正确账号密码并登录"],
                        "expected_results": ["1. 登录成功并跳转到首页"],
                    }
                ]
            },
            ensure_ascii=False,
        )

        def fake_chain_runner(**kwargs):
            events.append("chain")
            captured.update(kwargs)
            kwargs["on_requirement_analysis_result"](requirement_analysis_json)
            kwargs["on_case_names_result"](case_names_json)
            kwargs["on_detailed_cases_progress"](detailed_cases_after_first_batch, "登录", 1, 2)
            kwargs["on_detailed_cases_progress"](detailed_cases_json, "项目管理", 2, 2)
            return chain_result_cls(
                requirement_analysis_output=requirement_analysis_json,
                case_names_output=case_names_json,
                detailed_cases_output=detailed_cases_json,
            )

        skill_syncer = FakeSkillSyncer()
        executor = executor_cls(
            nanobot_config=NanobotConfig(
                runtime_root="D:/tmp/nanobot-runtime",
            ),
            chain_runner=fake_chain_runner,
            skill_syncer=skill_syncer,
        )

        result = executor.execute(
            task,
            datetime.fromisoformat("2026-06-23T10:00:00+08:00"),
            progress_events.append,
        )

        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertEqual(result.output_yaml, detailed_cases_json)
        self.assertEqual(len(progress_events), 4)
        self.assertEqual(progress_events[0].current_stage, "requirement_analysis")
        self.assertEqual(progress_events[1].current_stage, "case_names")
        self.assertEqual(progress_events[2].current_stage, "detailed_cases")
        self.assertEqual(progress_events[3].current_stage, "detailed_cases")
        self.assertEqual(progress_events[0].stage_status, "running")
        self.assertEqual(progress_events[1].stage_status, "running")
        self.assertEqual(progress_events[2].stage_status, "running")
        self.assertEqual(progress_events[3].stage_status, "running")
        self.assertEqual(progress_events[0].output_yaml, '{"cases":[]}')
        self.assertEqual(progress_events[1].output_yaml, '{"cases":[]}')
        self.assertEqual(progress_events[2].output_yaml, detailed_cases_after_first_batch)
        self.assertEqual(progress_events[3].output_yaml, detailed_cases_json)
        self.assertEqual(captured["session_key"], "run-functional-1")
        self.assertEqual(
            Path(str(captured["workspace"])),
            Path("D:/tmp/nanobot-runtime/workspaces/project-project-1"),
        )
        self.assertEqual(events, ["sync", "chain"])
        self.assertEqual(skill_syncer.project_id, "project-1")
        self.assertEqual(skill_syncer.workspace, Path("D:/tmp/nanobot-runtime/workspaces/project-project-1"))
        self.assertTrue(str(captured["config_path"]).endswith("nanobot.template.json"))
        self.assertEqual(captured["analysis_skill_name"], "solution-test-point-analyzer")
        self.assertEqual(captured["case_name_skill_name"], "test-case-name-extractor")
        self.assertEqual(captured["detailed_case_skill_name"], "detailed-test-case-generator")

        first_config = json.loads(progress_events[0].intermediate_json_text)
        second_config = json.loads(progress_events[1].intermediate_json_text)
        final_config = json.loads(result.intermediate_json_text)
        self.assertNotIn("enhancedText", first_config)
        self.assertIsNotNone(first_config["requirementAnalysis"])
        self.assertIsNone(first_config["caseNames"])
        self.assertIsNotNone(second_config["caseNames"])
        self.assertNotIn("enhancedText", final_config)
        self.assertEqual(final_config["caseNames"]["categories"][0]["model"], "登录")
        self.assertEqual(final_config["caseNames"]["categories"][1]["model"], "项目管理")

        summary = json.loads(result.result_summary_json)
        self.assertEqual(summary["status"], "success")
        self.assertEqual(summary["taskType"], "functional_case_generate")
        self.assertEqual(summary["documentType"], "text")
        self.assertEqual(summary["sourceType"], "text")
        self.assertEqual(summary["caseCount"], 2)

    def test_execute_returns_failed_result_for_unsupported_functional_document_type(self) -> None:
        executor_cls = getattr(executor_module, "FunctionalCaseNanobotExecutor", None)
        self.assertIsNotNone(executor_cls)
        if executor_cls is None:
            return

        task = self._make_task(source_type="text", document_type="richtext")
        executor = executor_cls(
            nanobot_config=NanobotConfig(),
            chain_runner=lambda **kwargs: None,
        )

        result = executor.execute(
            task,
            datetime.fromisoformat("2026-06-23T10:00:00+08:00"),
            lambda progress: None,
        )

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("richtext", result.error_message or "")

    def test_execute_accepts_word_document_type_and_uses_source_content(self) -> None:
        executor_cls = getattr(executor_module, "FunctionalCaseNanobotExecutor", None)
        self.assertIsNotNone(executor_cls)
        if executor_cls is None:
            return

        task = self._make_task(source_type="openapi", document_type="word")
        captured: dict[str, object] = {}

        def fake_chain_runner(**kwargs):
            captured.update(kwargs)
            kwargs["on_requirement_analysis_result"]("{}")
            kwargs["on_case_names_result"]('{"categories":[]}')
            return FunctionalChainRunResult(
                requirement_analysis_output="{}",
                case_names_output='{"categories":[]}',
                detailed_cases_output='{"cases":[]}',
            )

        executor = executor_cls(
            nanobot_config=NanobotConfig(runtime_root="D:/tmp/nanobot-runtime"),
            chain_runner=fake_chain_runner,
        )

        result = executor.execute(
            task,
            datetime.fromisoformat("2026-06-23T10:00:00+08:00"),
            lambda progress: None,
        )

        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertEqual(captured["source_text"], task.payload.source_content)
        summary = json.loads(result.result_summary_json)
        self.assertEqual(summary["documentType"], "word")
        self.assertEqual(summary["sourceType"], "word")

    def test_execute_checkpoint_requirement_analysis_uses_source_content_without_enhanced_stage(self) -> None:
        executor_cls = getattr(executor_module, "FunctionalCaseNanobotExecutor", None)
        self.assertIsNotNone(executor_cls)
        if executor_cls is None:
            return

        progress_events: list[TaskProgress] = []
        captured: dict[str, object] = {}
        requirement_analysis_json = json.dumps(
            {
                "Platform_core_functions": ["登录"],
                "Target_understanding": ["覆盖登录链路"],
                "Risk_point_prediction": ["认证失败"],
                "function_flow": ["输入账号密码", "登录成功"],
                "Scene_Design": [{"scene_type": "功能场景"}],
            },
            ensure_ascii=False,
        )

        def fake_skill_runner(**kwargs) -> str:
            captured.update(kwargs)
            return requirement_analysis_json

        task = self._make_task(
            checkpoint_enabled=True,
            current_stage="requirement_analysis",
            config_json="{}",
        )

        executor = executor_cls(
            nanobot_config=NanobotConfig(),
            chain_runner=lambda **kwargs: None,
            skill_runner=fake_skill_runner,
        )

        result = executor.execute(
            task,
            datetime.fromisoformat("2026-06-23T10:00:00+08:00"),
            progress_events.append,
        )

        self.assertIsNone(result)
        self.assertEqual(len(progress_events), 1)
        self.assertEqual(progress_events[0].current_stage, "requirement_analysis")
        self.assertEqual(progress_events[0].stage_status, "waiting_review")
        config = json.loads(progress_events[0].intermediate_json_text)
        self.assertEqual(captured["input_text"], task.payload.source_content)
        self.assertEqual(captured["skill_name"], "solution-test-point-analyzer")
        self.assertIn(task.payload.extra_instruction, captured["extra_instruction"])
        self.assertIn(FUNCTIONAL_ANALYSIS_JSON_ONLY_INSTRUCTION, captured["extra_instruction"])
        self.assertNotIn("enhancedText", config)
        self.assertEqual(config["requirementAnalysis"]["Platform_core_functions"], ["登录"])
        self.assertIsNone(config["caseNames"])

    def test_execute_checkpoint_requirement_analysis_ignores_legacy_enhanced_text_and_returns_none(self) -> None:
        executor_cls = getattr(executor_module, "FunctionalCaseNanobotExecutor", None)
        self.assertIsNotNone(executor_cls)
        if executor_cls is None:
            return

        progress_events: list[TaskProgress] = []
        captured: dict[str, object] = {}
        requirement_analysis_json = json.dumps(
            {
                "Platform_core_functions": ["登录"],
                "Target_understanding": ["覆盖登录链路"],
                "Risk_point_prediction": ["认证失败"],
                "function_flow": ["输入账号密码", "登录成功"],
                "Scene_Design": [{"scene_type": "功能场景"}],
            },
            ensure_ascii=False,
        )

        def fake_skill_runner(**kwargs) -> str:
            captured.update(kwargs)
            return requirement_analysis_json

        task = self._make_task(
            checkpoint_enabled=True,
            current_stage="requirement_analysis",
            config_json=json.dumps(
                {
                    "enhancedText": "这是审核后的增强文本",
                    "requirementAnalysis": None,
                    "caseNames": None,
                },
                ensure_ascii=False,
            ),
        )
        executor = executor_cls(
            nanobot_config=NanobotConfig(
                runtime_root="D:/tmp/nanobot-runtime",
            ),
            chain_runner=lambda **kwargs: None,
            skill_runner=fake_skill_runner,
        )

        result = executor.execute(
            task,
            datetime.fromisoformat("2026-06-23T10:00:00+08:00"),
            progress_events.append,
        )

        self.assertIsNone(result)
        self.assertEqual(captured["input_text"], task.payload.source_content)
        self.assertEqual(captured["skill_name"], "solution-test-point-analyzer")
        self.assertIn(task.payload.extra_instruction, captured["extra_instruction"])
        self.assertIn(FUNCTIONAL_ANALYSIS_JSON_ONLY_INSTRUCTION, captured["extra_instruction"])
        self.assertEqual(captured["session_key"], "run-functional-1")
        self.assertTrue(str(captured["config_path"]).endswith("nanobot.template.json"))
        self.assertEqual(
            Path(str(captured["workspace"])),
            Path("D:/tmp/nanobot-runtime/workspaces/project-project-1"),
        )
        self.assertEqual(len(progress_events), 1)
        self.assertEqual(progress_events[0].current_stage, "requirement_analysis")
        self.assertEqual(progress_events[0].stage_status, "waiting_review")
        config = json.loads(progress_events[0].intermediate_json_text)
        self.assertNotIn("enhancedText", config)
        self.assertIsNotNone(config["requirementAnalysis"])
        self.assertIsNone(config["caseNames"])

    def test_execute_checkpoint_requirement_analysis_ignores_invalid_old_config(self) -> None:
        executor_cls = getattr(executor_module, "FunctionalCaseNanobotExecutor", None)
        self.assertIsNotNone(executor_cls)
        if executor_cls is None:
            return

        progress_events: list[TaskProgress] = []
        task = self._make_task(
            checkpoint_enabled=True,
            current_stage="requirement_analysis",
            config_json="not-json",
        )
        executor = executor_cls(
            nanobot_config=NanobotConfig(),
            chain_runner=lambda **kwargs: None,
            skill_runner=lambda **kwargs: '{"Platform_core_functions": []}',
        )

        result = executor.execute(
            task,
            datetime.fromisoformat("2026-06-23T10:00:00+08:00"),
            progress_events.append,
        )

        self.assertIsNone(result)
        self.assertEqual(1, len(progress_events))
        self.assertEqual("waiting_review", progress_events[0].stage_status)

    def test_execute_checkpoint_case_names_uses_saved_requirement_analysis_and_returns_none(self) -> None:
        executor_cls = getattr(executor_module, "FunctionalCaseNanobotExecutor", None)
        self.assertIsNotNone(executor_cls)
        if executor_cls is None:
            return

        progress_events: list[TaskProgress] = []
        captured: dict[str, object] = {}
        requirement_analysis = {
            "Platform_core_functions": ["登录"],
            "Target_understanding": ["覆盖登录链路"],
            "Risk_point_prediction": ["认证失败"],
            "function_flow": ["输入账号密码", "登录成功"],
            "Scene_Design": [{"scene_type": "功能场景"}],
        }
        case_names_json = json.dumps(
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

        def fake_skill_runner(**kwargs) -> str:
            captured.update(kwargs)
            return case_names_json

        task = self._make_task(
            checkpoint_enabled=True,
            current_stage="case_names",
            config_json=json.dumps(
                {
                    "requirementAnalysis": requirement_analysis,
                    "caseNames": None,
                },
                ensure_ascii=False,
            ),
        )
        executor = executor_cls(
            nanobot_config=NanobotConfig(),
            chain_runner=lambda **kwargs: None,
            skill_runner=fake_skill_runner,
        )

        result = executor.execute(
            task,
            datetime.fromisoformat("2026-06-23T10:00:00+08:00"),
            progress_events.append,
        )

        self.assertIsNone(result)
        self.assertEqual(captured["skill_name"], "test-case-name-extractor")
        self.assertIn(task.payload.extra_instruction, captured["extra_instruction"])
        self.assertIn(FUNCTIONAL_CASE_NAMES_JSON_ONLY_INSTRUCTION, captured["extra_instruction"])
        self.assertEqual(captured["input_text"], json.dumps(requirement_analysis, ensure_ascii=False))
        self.assertEqual(len(progress_events), 1)
        self.assertEqual(progress_events[0].current_stage, "case_names")
        self.assertEqual(progress_events[0].stage_status, "waiting_review")
        config = json.loads(progress_events[0].intermediate_json_text)
        self.assertIsNotNone(config["requirementAnalysis"])
        self.assertIsNotNone(config["caseNames"])

    def test_execute_checkpoint_detailed_cases_resumes_from_config_and_returns_success(self) -> None:
        executor_cls = getattr(executor_module, "FunctionalCaseNanobotExecutor", None)
        self.assertIsNotNone(executor_cls)
        if executor_cls is None:
            return

        progress_events: list[TaskProgress] = []
        captured: dict[str, object] = {}
        requirement_analysis = {
            "Platform_core_functions": ["登录", "项目管理"],
            "Target_understanding": ["覆盖核心业务"],
            "Risk_point_prediction": ["权限错误"],
            "function_flow": ["登录", "进入项目列表", "新增项目"],
            "Scene_Design": [{"scene_type": "功能场景"}],
        }
        case_names = {
            "categories": [
                {
                    "model": "登录",
                    "data": [
                        {
                            "test_model": "功能场景",
                            "test_points": [{"case_name": "验证登录成功"}],
                        }
                    ],
                },
                {
                    "model": "项目管理",
                    "data": [
                        {
                            "test_model": "功能场景",
                            "test_points": [{"case_name": "验证项目新增成功"}],
                        }
                    ],
                },
            ]
        }
        first_batch_json = json.dumps(
            {
                "cases": [
                    {
                        "case_module": "登录",
                        "case_title": "验证登录成功",
                        "case_type": "功能测试",
                        "priority": "1",
                        "precondition": ["1. 用户已进入登录页"],
                        "test_steps": ["1. 输入正确账号密码并登录"],
                        "expected_results": ["1. 登录成功并跳转到首页"],
                    }
                ]
            },
            ensure_ascii=False,
        )
        final_batch_json = json.dumps(
            {
                "cases": [
                    {
                        "case_module": "登录",
                        "case_title": "验证登录成功",
                        "case_type": "功能测试",
                        "priority": "1",
                        "precondition": ["1. 用户已进入登录页"],
                        "test_steps": ["1. 输入正确账号密码并登录"],
                        "expected_results": ["1. 登录成功并跳转到首页"],
                    },
                    {
                        "case_module": "项目管理",
                        "case_title": "验证项目新增成功",
                        "case_type": "功能测试",
                        "priority": "1",
                        "precondition": ["1. 用户已成功登录"],
                        "test_steps": ["1. 新增项目并提交"],
                        "expected_results": ["1. 项目新增成功并展示在列表中"],
                    },
                ]
            },
            ensure_ascii=False,
        )

        def fake_detailed_batch_runner(**kwargs) -> str:
            captured.update(kwargs)
            kwargs["on_progress"](first_batch_json, "登录", 1, 2)
            kwargs["on_progress"](final_batch_json, "项目管理", 2, 2)
            return final_batch_json

        task = self._make_task(
            checkpoint_enabled=True,
            current_stage="detailed_cases",
            config_json=json.dumps(
                {
                    "requirementAnalysis": requirement_analysis,
                    "caseNames": case_names,
                },
                ensure_ascii=False,
            ),
        )
        executor = executor_cls(
            nanobot_config=NanobotConfig(),
            chain_runner=lambda **kwargs: None,
            detailed_batch_runner=fake_detailed_batch_runner,
        )

        result = executor.execute(
            task,
            datetime.fromisoformat("2026-06-23T10:00:00+08:00"),
            progress_events.append,
        )

        self.assertEqual(captured["skill_name"], "detailed-test-case-generator")
        self.assertEqual(captured["requirement_analysis_json"], json.dumps(requirement_analysis, ensure_ascii=False))
        self.assertEqual(captured["case_names_json"], json.dumps(case_names, ensure_ascii=False))
        self.assertEqual(len(progress_events), 2)
        self.assertEqual(progress_events[0].current_stage, "detailed_cases")
        self.assertEqual(progress_events[0].stage_status, "running")
        self.assertEqual(progress_events[1].output_yaml, final_batch_json)
        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertEqual(result.output_yaml, final_batch_json)
        final_config = json.loads(result.intermediate_json_text)
        self.assertNotIn("enhancedText", final_config)
        self.assertEqual(len(final_config["caseNames"]["categories"]), 2)

    def test_execute_uses_task_scoped_nanobot_config_when_llm_credentials_exist(self) -> None:
        executor_cls = getattr(executor_module, "FunctionalCaseNanobotExecutor", None)
        self.assertIsNotNone(executor_cls)
        if executor_cls is None:
            return

        task = self._make_task()
        task.payload.llm_credentials = LlmCredentials(
            model="gpt-5.4-mini",
            api_key="platform-key",
            base_url="https://example.test/v1",
        )
        captured: dict[str, object] = {}
        requirement_analysis_json = json.dumps(
            {
                "Platform_core_functions": ["登录"],
                "Target_understanding": ["覆盖核心业务"],
                "Risk_point_prediction": ["权限错误"],
                "function_flow": ["登录", "进入项目列表"],
                "Scene_Design": [{"scene_type": "功能场景"}],
            },
            ensure_ascii=False,
        )
        case_names_json = json.dumps(
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
        detailed_cases_json = json.dumps({"cases": []}, ensure_ascii=False)

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

            def fake_chain_runner(**kwargs):
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
                return FunctionalChainRunResult(
                    requirement_analysis_output=requirement_analysis_json,
                    case_names_output=case_names_json,
                    detailed_cases_output=detailed_cases_json,
                )

            executor = executor_cls(
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
