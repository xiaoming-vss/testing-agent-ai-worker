import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from testing_agent_ai_worker.config.models import NanobotConfig
from testing_agent_ai_worker.models.execution import TaskProgress, TaskResult, TaskStatus
from testing_agent_ai_worker.models.task import Task, TaskPayload
from testing_agent_ai_worker.tasks.requirement_analysis.chain import (
    RequirementAnalysisChainRunResult,
)
from testing_agent_ai_worker.tasks.requirement_analysis.executor import (
    REQUIREMENT_ANALYSIS_FIRST_SKILL_NAME,
    REQUIREMENT_ANALYSIS_SECOND_SKILL_NAME,
    REQUIREMENT_ANALYSIS_THIRD_SKILL_NAME,
    RequirementAnalysisNanobotExecutor,
)
from testing_agent_ai_worker.worker.dispatcher import WorkerTaskDispatcherExecutor


class FakeSourceDownloader:
    def __init__(
        self,
        saved_path: str = "D:/tmp/nanobot-runtime/workspaces/project-project-1/inputs/worker-task-1/source.docx",
    ) -> None:
        self.saved_path = Path(saved_path)
        self.calls: list[dict[str, object]] = []

    def download_source(
        self, *, document_download_url: str, document_type: str, task: Task, workspace: Path
    ) -> Path:
        self.calls.append(
            {
                "document_download_url": document_download_url,
                "document_type": document_type,
                "task": task,
                "workspace": workspace,
            }
        )
        return self.saved_path


class RequirementAnalysisExecutorTests(unittest.TestCase):
    def _make_task(
        self,
        *,
        task_type: str = "requirement_analysis",
        source_type: str = "text",
        document_type: str = "word",
        config_json: str = '{"seed":true}',
        source_content: str = "需求正文内容",
        document_download_url: str = "/internal/ai-worker/tasks/worker-task-1/requirement-document",
        checkpoint_enabled: bool = False,
        current_stage: str = "",
    ) -> Task:
        return Task(
            claim_id="claim-requirement-1",
            task_id="worker-task-1",
            run_id="run-1",
            generate_task_id="task-1",
            task_type=task_type,
            project_id="project-1",
            sprint_id="sprint-1",
            requirement_id="requirement-1",
            checkpoint_enabled=checkpoint_enabled,
            current_stage=current_stage,
            config_json=config_json,
            payload=TaskPayload(
                openapi_content="需求正文内容",
                source_content=source_content,
                source_type=source_type,
                document_type=document_type,
                extra_instruction="重点分析异常场景和歧义点",
                document_download_url=document_download_url,
            ),
        )

    def test_execute_runs_three_step_chain_submits_progress_and_returns_success(self) -> None:
        executor_cls = RequirementAnalysisNanobotExecutor
        result_cls = RequirementAnalysisChainRunResult
        self.assertIsNotNone(executor_cls)
        self.assertIsNotNone(result_cls)
        if executor_cls is None or result_cls is None:
            return

        task = self._make_task()
        progress_events: list[TaskProgress] = []
        captured: dict[str, object] = {}
        events: list[str] = []

        def fake_chain_runner(**kwargs):
            events.append("chain")
            captured.update(kwargs)
            kwargs["on_first_step_result"]("normalized requirement text")
            kwargs["on_second_step_result"]("first analysis json")
            return result_cls(
                first_step_output="normalized requirement text",
                second_step_output="first analysis json",
                final_output="analysis:\n  summary: done",
            )

        source_downloader = FakeSourceDownloader()
        executor = executor_cls(
            nanobot_config=NanobotConfig(runtime_root="D:/tmp/nanobot-runtime"),
            chain_runner=fake_chain_runner,
            source_downloader=source_downloader,
        )

        result = executor.execute(
            task,
            datetime.fromisoformat("2026-06-30T10:00:00+08:00"),
            progress_events.append,
        )

        self.assertEqual(events, ["chain"])
        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertEqual(result.output_yaml, "analysis:\n  summary: done")
        final_config = json.loads(result.intermediate_json_text)
        self.assertNotIn("analysisConfig", final_config)
        self.assertEqual(final_config["firstStepOutput"], "normalized requirement text")
        self.assertEqual(final_config["secondStepOutput"], "first analysis json")
        self.assertEqual(len(progress_events), 2)
        self.assertEqual(progress_events[0].current_stage, "extracting_text")
        self.assertEqual(progress_events[0].stage_status, "running")
        self.assertEqual(progress_events[0].output_yaml, "")
        first_progress_config = json.loads(progress_events[0].intermediate_json_text)
        self.assertEqual(first_progress_config["firstStepOutput"], "normalized requirement text")
        self.assertNotIn("secondStepOutput", first_progress_config)
        self.assertEqual(progress_events[1].current_stage, "writing_requirement")
        self.assertEqual(progress_events[1].stage_status, "running")
        self.assertEqual(progress_events[1].output_yaml, "")
        second_progress_config = json.loads(progress_events[1].intermediate_json_text)
        self.assertEqual(second_progress_config["firstStepOutput"], "normalized requirement text")
        self.assertEqual(second_progress_config["secondStepOutput"], "first analysis json")
        self.assertEqual(captured["source_text"], str(source_downloader.saved_path))
        self.assertEqual(captured["session_key"], "run-1")
        self.assertEqual(captured["first_skill_name"], "extract-docx-enhanced-text")
        self.assertEqual(captured["second_skill_name"], "prd-requirement-writing-skill")
        self.assertEqual(captured["third_skill_name"], "prd-feature-understanding-skill")
        self.assertEqual(captured["extra_instruction"], "重点分析异常场景和歧义点")
        self.assertEqual(len(source_downloader.calls), 1)
        self.assertEqual(
            source_downloader.calls[0]["document_download_url"],
            "/internal/ai-worker/tasks/worker-task-1/requirement-document",
        )
        self.assertEqual(source_downloader.calls[0]["document_type"], "word")
        self.assertEqual(source_downloader.calls[0]["task"], task)
        self.assertEqual(
            source_downloader.calls[0]["workspace"],
            Path("D:/tmp/nanobot-runtime/workspaces/project-project-1"),
        )

    def test_execute_uses_document_download_url_not_source_content_for_download(self) -> None:
        source_downloader = FakeSourceDownloader(
            "D:/tmp/nanobot-runtime/workspaces/project-project-1/inputs/worker-task-1/source.docx"
        )

        def fake_chain_runner(**kwargs):
            kwargs["on_first_step_result"]("normalized requirement text")
            return RequirementAnalysisChainRunResult(
                first_step_output="normalized requirement text",
                second_step_output="analysis json",
                final_output="analysis:\n  summary: done",
            )

        executor = RequirementAnalysisNanobotExecutor(
            nanobot_config=NanobotConfig(runtime_root="D:/tmp/nanobot-runtime"),
            chain_runner=fake_chain_runner,
            source_downloader=source_downloader,
        )
        result = executor.execute(
            self._make_task(
                source_content="/v1/requirements/requirement-1/download",
                document_download_url="/internal/ai-worker/tasks/worker-task-1/requirement-document",
            ),
            datetime.fromisoformat("2026-06-30T10:00:00+08:00"),
            lambda progress: None,
        )

        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertEqual(
            source_downloader.calls[0]["document_download_url"],
            "/internal/ai-worker/tasks/worker-task-1/requirement-document",
        )
        self.assertNotEqual(
            source_downloader.calls[0]["document_download_url"],
            "/v1/requirements/requirement-1/download",
        )

    def test_execute_checkpoint_extracting_text_returns_none_for_review(self) -> None:
        progress_events: list[TaskProgress] = []
        captured: dict[str, object] = {}
        source_downloader = FakeSourceDownloader(
            "D:/tmp/nanobot-runtime/workspaces/project-project-1/inputs/worker-task-1/source.docx"
        )

        def fake_skill_runner(**kwargs) -> str:
            captured.update(kwargs)
            return "审核前抽取文本"

        executor = RequirementAnalysisNanobotExecutor(
            nanobot_config=NanobotConfig(runtime_root="D:/tmp/nanobot-runtime"),
            chain_runner=lambda **kwargs: None,
            skill_runner=fake_skill_runner,
            source_downloader=source_downloader,
        )
        result = executor.execute(
            self._make_task(
                checkpoint_enabled=True,
                current_stage="extracting_text",
                config_json="{}",
            ),
            datetime.fromisoformat("2026-06-30T10:00:00+08:00"),
            progress_events.append,
        )

        self.assertIsNone(result)
        self.assertEqual(len(source_downloader.calls), 1)
        self.assertEqual(captured["input_text"], str(source_downloader.saved_path))
        self.assertEqual(captured["skill_name"], "extract-docx-enhanced-text")
        self.assertEqual(len(progress_events), 1)
        self.assertEqual(progress_events[0].current_stage, "extracting_text")
        self.assertEqual(progress_events[0].stage_status, "waiting_review")
        config = json.loads(progress_events[0].intermediate_json_text)
        self.assertEqual(config, {"firstStepOutput": "审核前抽取文本"})

    def test_execute_checkpoint_when_current_stage_is_set_even_if_flag_is_false(self) -> None:
        progress_events: list[TaskProgress] = []
        captured: dict[str, object] = {}
        source_downloader = FakeSourceDownloader(
            "D:/tmp/nanobot-runtime/workspaces/project-project-1/inputs/worker-task-1/source.docx"
        )

        def fake_skill_runner(**kwargs) -> str:
            captured.update(kwargs)
            return "按阶段进入卡点的抽取文本"

        executor = RequirementAnalysisNanobotExecutor(
            nanobot_config=NanobotConfig(runtime_root="D:/tmp/nanobot-runtime"),
            chain_runner=lambda **kwargs: None,
            skill_runner=fake_skill_runner,
            source_downloader=source_downloader,
        )
        result = executor.execute(
            self._make_task(
                checkpoint_enabled=False,
                current_stage="extracting_text",
                config_json="{}",
            ),
            datetime.fromisoformat("2026-06-30T10:00:00+08:00"),
            progress_events.append,
        )

        self.assertIsNone(result)
        self.assertEqual(captured["skill_name"], "extract-docx-enhanced-text")
        self.assertEqual(progress_events[0].stage_status, "waiting_review")

    def test_execute_checkpoint_defaults_empty_stage_to_extracting_text(self) -> None:
        progress_events: list[TaskProgress] = []
        captured: dict[str, object] = {}
        source_downloader = FakeSourceDownloader(
            "D:/tmp/nanobot-runtime/workspaces/project-project-1/inputs/worker-task-1/source.docx"
        )

        def fake_skill_runner(**kwargs) -> str:
            captured.update(kwargs)
            return "默认第一阶段抽取文本"

        executor = RequirementAnalysisNanobotExecutor(
            nanobot_config=NanobotConfig(runtime_root="D:/tmp/nanobot-runtime"),
            chain_runner=lambda **kwargs: None,
            skill_runner=fake_skill_runner,
            source_downloader=source_downloader,
        )
        result = executor.execute(
            self._make_task(
                checkpoint_enabled=True,
                current_stage="",
                config_json="{}",
            ),
            datetime.fromisoformat("2026-06-30T10:00:00+08:00"),
            progress_events.append,
        )

        self.assertIsNone(result)
        self.assertEqual(captured["skill_name"], "extract-docx-enhanced-text")
        self.assertEqual(progress_events[0].current_stage, "extracting_text")
        self.assertEqual(progress_events[0].stage_status, "waiting_review")

    def test_execute_checkpoint_writing_requirement_uses_reviewed_first_step(self) -> None:
        progress_events: list[TaskProgress] = []
        captured: dict[str, object] = {}
        source_downloader = FakeSourceDownloader()

        def fake_skill_runner(**kwargs) -> str:
            captured.update(kwargs)
            return "审核前需求流程稿"

        executor = RequirementAnalysisNanobotExecutor(
            nanobot_config=NanobotConfig(runtime_root="D:/tmp/nanobot-runtime"),
            chain_runner=lambda **kwargs: None,
            skill_runner=fake_skill_runner,
            source_downloader=source_downloader,
        )
        result = executor.execute(
            self._make_task(
                checkpoint_enabled=True,
                current_stage="writing_requirement",
                config_json=json.dumps({"firstStepOutput": "审核后的抽取文本"}, ensure_ascii=False),
            ),
            datetime.fromisoformat("2026-06-30T10:00:00+08:00"),
            progress_events.append,
        )

        self.assertIsNone(result)
        self.assertEqual(source_downloader.calls, [])
        self.assertEqual(captured["input_text"], "审核后的抽取文本")
        self.assertEqual(captured["skill_name"], "prd-requirement-writing-skill")
        self.assertEqual(len(progress_events), 1)
        self.assertEqual(progress_events[0].current_stage, "writing_requirement")
        self.assertEqual(progress_events[0].stage_status, "waiting_review")
        config = json.loads(progress_events[0].intermediate_json_text)
        self.assertEqual(config["firstStepOutput"], "审核后的抽取文本")
        self.assertEqual(config["secondStepOutput"], "审核前需求流程稿")

    def test_execute_checkpoint_revises_extracting_text_without_downloading_again(self) -> None:
        progress_events: list[TaskProgress] = []
        captured: dict[str, object] = {}
        source_downloader = FakeSourceDownloader()

        def fake_skill_runner(**kwargs) -> str:
            captured.update(kwargs)
            return "修改后的抽取文本"

        executor = RequirementAnalysisNanobotExecutor(
            nanobot_config=NanobotConfig(runtime_root="D:/tmp/nanobot-runtime"),
            chain_runner=lambda **kwargs: None,
            skill_runner=fake_skill_runner,
            source_downloader=source_downloader,
        )
        result = executor.execute(
            self._make_task(
                checkpoint_enabled=True,
                current_stage="extracting_text",
                config_json=json.dumps(
                    {
                        "firstStepOutput": "当前抽取文本",
                        "revisionInstruction": "补充图片中的流程信息",
                    },
                    ensure_ascii=False,
                ),
            ),
            datetime.fromisoformat("2026-06-30T10:00:00+08:00"),
            progress_events.append,
        )

        self.assertIsNone(result)
        self.assertEqual(source_downloader.calls, [])
        self.assertEqual(captured["skill_name"], "extract-docx-enhanced-text")
        self.assertIn("当前抽取文本", captured["input_text"])
        self.assertIn("补充图片中的流程信息", captured["input_text"])
        self.assertEqual(progress_events[0].stage_status, "waiting_review")
        config = json.loads(progress_events[0].intermediate_json_text)
        self.assertEqual(config, {"firstStepOutput": "修改后的抽取文本"})

    def test_execute_checkpoint_revises_writing_requirement_in_same_stage(self) -> None:
        progress_events: list[TaskProgress] = []
        captured: dict[str, object] = {}
        source_downloader = FakeSourceDownloader()

        def fake_skill_runner(**kwargs) -> str:
            captured.update(kwargs)
            return "修改后的需求流程稿"

        executor = RequirementAnalysisNanobotExecutor(
            nanobot_config=NanobotConfig(runtime_root="D:/tmp/nanobot-runtime"),
            chain_runner=lambda **kwargs: None,
            skill_runner=fake_skill_runner,
            source_downloader=source_downloader,
        )
        result = executor.execute(
            self._make_task(
                checkpoint_enabled=True,
                current_stage="writing_requirement",
                config_json=json.dumps(
                    {
                        "firstStepOutput": "审核后的抽取文本",
                        "secondStepOutput": "当前需求流程稿",
                        "revisionInstruction": "增加异常和边界场景",
                    },
                    ensure_ascii=False,
                ),
            ),
            datetime.fromisoformat("2026-06-30T10:00:00+08:00"),
            progress_events.append,
        )

        self.assertIsNone(result)
        self.assertEqual(source_downloader.calls, [])
        self.assertEqual(captured["skill_name"], "prd-requirement-writing-skill")
        self.assertIn("当前需求流程稿", captured["input_text"])
        self.assertIn("增加异常和边界场景", captured["input_text"])
        self.assertEqual(progress_events[0].current_stage, "writing_requirement")
        self.assertEqual(progress_events[0].stage_status, "waiting_review")
        config = json.loads(progress_events[0].intermediate_json_text)
        self.assertEqual(config["firstStepOutput"], "审核后的抽取文本")
        self.assertEqual(config["secondStepOutput"], "修改后的需求流程稿")
        self.assertNotIn("revisionInstruction", config)

    def test_execute_checkpoint_feature_understanding_completes_from_reviewed_config(self) -> None:
        progress_events: list[TaskProgress] = []
        captured: dict[str, object] = {}
        source_downloader = FakeSourceDownloader()

        def fake_skill_runner(**kwargs) -> str:
            captured.update(kwargs)
            return "analysis:\n  summary: done"

        executor = RequirementAnalysisNanobotExecutor(
            nanobot_config=NanobotConfig(runtime_root="D:/tmp/nanobot-runtime"),
            chain_runner=lambda **kwargs: None,
            skill_runner=fake_skill_runner,
            source_downloader=source_downloader,
        )
        result = executor.execute(
            self._make_task(
                checkpoint_enabled=True,
                current_stage="feature_understanding",
                config_json=json.dumps(
                    {
                        "firstStepOutput": "审核后的抽取文本",
                        "secondStepOutput": "审核后的需求流程稿",
                    },
                    ensure_ascii=False,
                ),
            ),
            datetime.fromisoformat("2026-06-30T10:00:00+08:00"),
            progress_events.append,
        )

        self.assertEqual(source_downloader.calls, [])
        self.assertEqual(progress_events, [])
        self.assertEqual(captured["input_text"], "审核后的需求流程稿")
        self.assertEqual(captured["skill_name"], "prd-feature-understanding-skill")
        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertEqual(result.output_yaml, "analysis:\n  summary: done")
        config = json.loads(result.intermediate_json_text)
        self.assertEqual(config["firstStepOutput"], "审核后的抽取文本")
        self.assertEqual(config["secondStepOutput"], "审核后的需求流程稿")

    def test_execute_checkpoint_revises_feature_understanding_final_output(self) -> None:
        progress_events: list[TaskProgress] = []
        captured: dict[str, object] = {}
        source_downloader = FakeSourceDownloader()

        def fake_skill_runner(**kwargs) -> str:
            captured.update(kwargs)
            return "analysis:\n  summary: 修改后的最终理解"

        executor = RequirementAnalysisNanobotExecutor(
            nanobot_config=NanobotConfig(runtime_root="D:/tmp/nanobot-runtime"),
            chain_runner=lambda **kwargs: None,
            skill_runner=fake_skill_runner,
            source_downloader=source_downloader,
        )
        result = executor.execute(
            self._make_task(
                checkpoint_enabled=True,
                current_stage="feature_understanding",
                config_json=json.dumps(
                    {
                        "firstStepOutput": "审核后的抽取文本",
                        "secondStepOutput": "审核后的需求流程稿",
                        "resultYaml": "analysis:\n  summary: 当前最终理解",
                        "revisionInstruction": "补充异常场景和验收口径",
                    },
                    ensure_ascii=False,
                ),
            ),
            datetime.fromisoformat("2026-06-30T10:00:00+08:00"),
            progress_events.append,
        )

        self.assertEqual(source_downloader.calls, [])
        self.assertEqual(progress_events, [])
        self.assertEqual(captured["skill_name"], "prd-feature-understanding-skill")
        self.assertIn("当前最终理解", captured["input_text"])
        self.assertIn("补充异常场景和验收口径", captured["input_text"])
        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertEqual(result.output_yaml, "analysis:\n  summary: 修改后的最终理解")
        config = json.loads(result.intermediate_json_text)
        self.assertEqual(config["firstStepOutput"], "审核后的抽取文本")
        self.assertEqual(config["secondStepOutput"], "审核后的需求流程稿")
        self.assertNotIn("revisionInstruction", config)
        self.assertNotIn("resultYaml", config)

    def test_default_skill_names_are_configured(self) -> None:
        self.assertEqual(REQUIREMENT_ANALYSIS_FIRST_SKILL_NAME, "extract-docx-enhanced-text")
        self.assertEqual(REQUIREMENT_ANALYSIS_SECOND_SKILL_NAME, "prd-requirement-writing-skill")
        self.assertEqual(REQUIREMENT_ANALYSIS_THIRD_SKILL_NAME, "prd-feature-understanding-skill")

    def test_execute_accepts_word_document_type(self) -> None:
        def fake_chain_runner(**kwargs):
            kwargs["on_first_step_result"]("docx normalized text")
            return RequirementAnalysisChainRunResult(
                first_step_output="docx normalized text",
                second_step_output="docx analysis json",
                final_output="analysis:\n  summary: docx done",
            )

        executor = RequirementAnalysisNanobotExecutor(
            nanobot_config=NanobotConfig(runtime_root="D:/tmp/nanobot-runtime"),
            chain_runner=fake_chain_runner,
            source_downloader=FakeSourceDownloader(
                "D:/tmp/nanobot-runtime/workspaces/project-project-1/inputs/worker-task-1/source.docx"
            ),
        )
        result = executor.execute(
            self._make_task(document_type="word"),
            datetime.fromisoformat("2026-06-30T10:00:00+08:00"),
            lambda progress: None,
        )

        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertEqual(result.output_yaml, "analysis:\n  summary: docx done")

    def test_execute_accepts_docx_document_type_alias(self) -> None:
        def fake_chain_runner(**kwargs):
            kwargs["on_first_step_result"]("docx normalized text")
            return RequirementAnalysisChainRunResult(
                first_step_output="docx normalized text",
                second_step_output="docx analysis json",
                final_output="analysis:\n  summary: docx alias done",
            )

        source_downloader = FakeSourceDownloader(
            "D:/tmp/nanobot-runtime/workspaces/project-project-1/inputs/worker-task-1/source.docx"
        )
        executor = RequirementAnalysisNanobotExecutor(
            nanobot_config=NanobotConfig(runtime_root="D:/tmp/nanobot-runtime"),
            chain_runner=fake_chain_runner,
            source_downloader=source_downloader,
        )
        result = executor.execute(
            self._make_task(document_type="docx"),
            datetime.fromisoformat("2026-06-30T10:00:00+08:00"),
            lambda progress: None,
        )

        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertEqual(result.output_yaml, "analysis:\n  summary: docx alias done")
        self.assertEqual(source_downloader.calls[0]["document_type"], "word")

    def test_execute_accepts_text_document_type(self) -> None:
        def fake_chain_runner(**kwargs):
            kwargs["on_first_step_result"]("txt normalized text")
            return RequirementAnalysisChainRunResult(
                first_step_output="txt normalized text",
                second_step_output="txt analysis json",
                final_output="analysis:\n  summary: txt done",
            )

        executor = RequirementAnalysisNanobotExecutor(
            nanobot_config=NanobotConfig(runtime_root="D:/tmp/nanobot-runtime"),
            chain_runner=fake_chain_runner,
            source_downloader=FakeSourceDownloader(
                "D:/tmp/nanobot-runtime/workspaces/project-project-1/inputs/worker-task-1/source.txt"
            ),
        )
        result = executor.execute(
            self._make_task(document_type="text"),
            datetime.fromisoformat("2026-06-30T10:00:00+08:00"),
            lambda progress: None,
        )

        self.assertEqual(result.status, TaskStatus.SUCCESS)
        self.assertEqual(result.output_yaml, "analysis:\n  summary: txt done")

    def test_execute_returns_failed_result_for_unsupported_document_type(self) -> None:
        executor_cls = RequirementAnalysisNanobotExecutor
        self.assertIsNotNone(executor_cls)
        if executor_cls is None:
            return

        executor = executor_cls(nanobot_config=NanobotConfig())
        result = executor.execute(
            self._make_task(document_type="richtext"),
            datetime.fromisoformat("2026-06-30T10:00:00+08:00"),
            lambda progress: None,
        )

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("不支持的 document_type", result.error_message)


class RequirementAnalysisDispatcherTests(unittest.TestCase):
    def test_dispatcher_routes_requirement_analysis_task(self) -> None:
        dispatcher_cls = WorkerTaskDispatcherExecutor
        self.assertIsNotNone(dispatcher_cls)
        if dispatcher_cls is None:
            return

        task = Task(
            task_id="worker-task-1",
            run_id="run-1",
            generate_task_id="task-1",
            task_type="requirement_analysis",
            payload=TaskPayload(
                openapi_content="需求正文内容",
                source_content="需求正文内容",
                source_type="text",
            ),
        )
        started_at = datetime.fromisoformat("2026-06-30T10:00:00+08:00")
        returned_result = TaskResult(
            task_id=task.task_id,
            run_id=task.run_id,
            generate_task_id=task.generate_task_id,
            status=TaskStatus.SUCCESS,
            started_at=started_at,
            finished_at=started_at,
        )
        calls: list[str] = []

        class FakeExecutor:
            def __init__(self, name: str, result: TaskResult | None = None) -> None:
                self.name = name
                self.result = result

            def execute(self, task, started_at, progress_callback):
                calls.append(self.name)
                return self.result

        dispatcher = dispatcher_cls(
            api_executor=FakeExecutor("api"),
            functional_executor=FakeExecutor("functional"),
            requirement_executor=FakeExecutor("requirement", returned_result),
        )

        result = dispatcher.execute(task, started_at, lambda progress: None)

        self.assertEqual(calls, ["requirement"])
        self.assertIs(result, returned_result)


if __name__ == "__main__":
    unittest.main()
