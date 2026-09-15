import sys
import unittest
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from testing_agent_ai_worker.models.task import Task, TaskPayload
from testing_agent_ai_worker.platform.task_source import HttpClaimTaskSource
from testing_agent_ai_worker.services.task_service import TaskService
from testing_agent_ai_worker.worker.poller import TaskPoller


class FakePlatformHttpClient:
    def __init__(self) -> None:
        self.timeout_seconds = 5.0
        self.claim_called = False
        self.snapshot_called = False
        self.credentials_called = False
        self.raise_on_credentials = False

    def post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any] | None:
        self.claim_called = True
        self.last_claim_path = path
        self.last_claim_body = json_body
        return {
            "id": "claim-lease-1",
            "taskId": "worker-task-1",
            "runId": "run-1",
            "generateTaskId": "generate-task-1",
            "taskType": "api_case_generate",
            "projectId": "project-1",
            "sprintId": "sprint-1",
            "requirementId": "req-1",
            "leaseSeconds": 30,
            "llmConnectionId": "conn-1",
        }

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        self.snapshot_called = True
        self.last_snapshot_path = path
        return {
            "run": {
                "taskId": "worker-task-1",
                "runId": "run-1",
                "generateTaskId": "generate-task-1",
                "taskType": "api_case_generate",
                "name": "OpenAPI 用例生成",
                "projectId": "project-1",
                "sprintId": "sprint-1",
                "requirementId": "req-1",
                "sourceType": "openapi",
                "sourceContent": '{"openapi":"3.0.0"}',
                "targetScope": "只处理登录与鉴权接口",
                "instruction": "只提取登录接口",
                "checkpointEnabled": True,
                "currentStage": "case_names",
                "configJson": '{"enhancedText":"审核后文本"}',
            }
        }

    def get_with_retry(
        self,
        path: str,
        max_retries: int = 3,
        backoff_base: float = 1.0,
    ) -> Any:
        if self.raise_on_credentials:
            raise RuntimeError("凭证接口不可用")
        self.credentials_called = True
        self.last_credentials_path = path
        return {
            "baseUrl": "https://test-llm.example.com/v1",
            "modelId": "gpt-4o",
            "apiKey": "sk-test",
        }


class TaskSourceTests(unittest.TestCase):
    def test_task_nanobot_session_key_uses_run_id_directly(self) -> None:
        payload = TaskPayload(openapi_content="{}")

        self.assertEqual(
            Task(
                claim_id="claim-1", task_id="task-1", run_id="run-1", payload=payload
            ).nanobot_session_key,
            "run-1",
        )
        self.assertEqual("", payload.source_type)

    def test_poll_task_returns_none_when_claim_returns_empty(self) -> None:
        class EmptyClaimClient(FakePlatformHttpClient):
            def post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any] | None:
                self.claim_called = True
                return None

        task_source = HttpClaimTaskSource(
            client=EmptyClaimClient(),
            claim_path="/internal/ai-worker/tasks/claim",
            snapshot_path_template="/internal/ai-worker/tasks/{task_id}/snapshot",
            llm_credentials_path_template="/internal/ai-worker/tasks/{task_id}/llm-credentials",
            worker_id="worker-local",
        )

        task = task_source.poll_task()

        self.assertIsNone(task)

    def test_poll_task_maps_platform_payload_to_domain_task(self) -> None:
        client = FakePlatformHttpClient()
        task_source = HttpClaimTaskSource(
            client=client,
            claim_path="/internal/ai-worker/tasks/claim",
            snapshot_path_template="/internal/ai-worker/tasks/{task_id}/snapshot",
            llm_credentials_path_template="/internal/ai-worker/tasks/{task_id}/llm-credentials",
            worker_id="worker-local",
        )

        task = task_source.poll_task()

        self.assertTrue(client.claim_called)
        self.assertTrue(client.snapshot_called)
        self.assertTrue(client.credentials_called)
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual("claim-lease-1", task.claim_id)
        self.assertEqual("worker-task-1", task.task_id)
        self.assertEqual("run-1", task.run_id)
        self.assertEqual("generate-task-1", task.generate_task_id)
        self.assertEqual("api_case_generate", task.task_type)
        self.assertEqual("project-1", task.project_id)
        self.assertEqual("sprint-1", task.sprint_id)
        self.assertEqual("req-1", task.requirement_id)
        self.assertEqual('{"openapi":"3.0.0"}', task.payload.openapi_content)
        self.assertEqual('{"openapi":"3.0.0"}', task.payload.source_content)
        self.assertEqual("openapi", task.payload.source_type)
        self.assertEqual("只处理登录与鉴权接口", task.payload.target_scope)
        self.assertEqual("只提取登录接口", task.payload.extra_instruction)
        self.assertTrue(task.checkpoint_enabled)
        self.assertEqual("case_names", task.current_stage)
        self.assertEqual('{"enhancedText":"审核后文本"}', task.config_json)
        self.assertEqual("api_case_generate", task.raw["claim"]["taskType"])
        self.assertEqual("OpenAPI 用例生成", task.raw["snapshot"]["run"]["name"])
        self.assertIsNotNone(task.payload.llm_credentials)
        assert task.payload.llm_credentials is not None
        self.assertEqual("gpt-4o", task.payload.llm_credentials.model)
        self.assertEqual("sk-test", task.payload.llm_credentials.api_key)
        self.assertEqual("https://test-llm.example.com/v1", task.payload.llm_credentials.base_url)
        self.assertIsNone(task.credential_error)
        self.assertTrue(task.has_credentials)

    def test_poll_task_uses_task_type_fallback_order(self) -> None:
        class FallbackTaskTypeClient(FakePlatformHttpClient):
            def post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any] | None:
                payload = super().post(path, json_body)
                assert payload is not None
                payload["taskType"] = "claim-task-type"
                return payload

            def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
                payload = super().get(path, params)
                assert payload is not None
                payload["taskType"] = ""
                payload["run"]["taskType"] = "snapshot-run-task-type"
                return payload

        task_source = HttpClaimTaskSource(
            client=FallbackTaskTypeClient(),
            claim_path="/internal/ai-worker/tasks/claim",
            snapshot_path_template="/internal/ai-worker/tasks/{task_id}/snapshot",
            llm_credentials_path_template="/internal/ai-worker/tasks/{task_id}/llm-credentials",
            worker_id="worker-local",
        )

        task = task_source.poll_task()

        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual("snapshot-run-task-type", task.task_type)

    def test_poll_task_accepts_checkpoint_fields_on_snapshot_top_level(self) -> None:
        class TopLevelCheckpointClient(FakePlatformHttpClient):
            def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
                payload = super().get(path, params)
                assert payload is not None
                payload["checkpointEnabled"] = True
                payload["currentStage"] = "requirement_analysis"
                payload["configJson"] = '{"enhancedText":"顶层审核文本"}'
                payload["run"].pop("checkpointEnabled")
                payload["run"].pop("currentStage")
                payload["run"].pop("configJson")
                return payload

        task_source = HttpClaimTaskSource(
            client=TopLevelCheckpointClient(),
            claim_path="/internal/ai-worker/tasks/claim",
            snapshot_path_template="/internal/ai-worker/tasks/{task_id}/snapshot",
            llm_credentials_path_template="/internal/ai-worker/tasks/{task_id}/llm-credentials",
            worker_id="worker-local",
        )

        task = task_source.poll_task()

        self.assertIsNotNone(task)
        assert task is not None
        self.assertTrue(task.checkpoint_enabled)
        self.assertEqual("requirement_analysis", task.current_stage)
        self.assertEqual('{"enhancedText":"顶层审核文本"}', task.config_json)

    def test_poll_task_uses_claim_checkpoint_fields_when_snapshot_omits_them(self) -> None:
        class ClaimCheckpointClient(FakePlatformHttpClient):
            def post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any] | None:
                payload = super().post(path, json_body)
                assert payload is not None
                payload["checkpointEnabled"] = True
                payload["currentStage"] = "enhanced_text"
                payload["configJson"] = '{"enhancedText":"来自 claim"}'
                return payload

            def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
                payload = super().get(path, params)
                assert payload is not None
                payload["run"].pop("checkpointEnabled")
                payload["run"].pop("currentStage")
                payload["run"].pop("configJson")
                return payload

        task_source = HttpClaimTaskSource(
            client=ClaimCheckpointClient(),
            claim_path="/internal/ai-worker/tasks/claim",
            snapshot_path_template="/internal/ai-worker/tasks/{task_id}/snapshot",
            llm_credentials_path_template="/internal/ai-worker/tasks/{task_id}/llm-credentials",
            worker_id="worker-local",
        )

        task = task_source.poll_task()

        self.assertIsNotNone(task)
        assert task is not None
        self.assertTrue(task.checkpoint_enabled)
        self.assertEqual("enhanced_text", task.current_stage)
        self.assertEqual('{"enhancedText":"来自 claim"}', task.config_json)

    def test_poll_task_snapshot_false_overrides_claim_checkpoint_true(self) -> None:
        class SnapshotDisablesCheckpointClient(FakePlatformHttpClient):
            def post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any] | None:
                payload = super().post(path, json_body)
                assert payload is not None
                payload["checkpointEnabled"] = True
                return payload

            def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
                payload = super().get(path, params)
                assert payload is not None
                payload["checkpointEnabled"] = False
                payload["run"].pop("checkpointEnabled", None)
                return payload

        task_source = HttpClaimTaskSource(
            client=SnapshotDisablesCheckpointClient(),
            claim_path="/internal/ai-worker/tasks/claim",
            snapshot_path_template="/internal/ai-worker/tasks/{task_id}/snapshot",
            llm_credentials_path_template="/internal/ai-worker/tasks/{task_id}/llm-credentials",
            worker_id="worker-local",
        )

        task = task_source.poll_task()

        self.assertIsNotNone(task)
        assert task is not None
        self.assertFalse(task.checkpoint_enabled)

    def test_poll_task_sets_credential_error_on_failure(self) -> None:
        client = FakePlatformHttpClient()
        client.raise_on_credentials = True
        task_source = HttpClaimTaskSource(
            client=client,
            claim_path="/internal/ai-worker/tasks/claim",
            snapshot_path_template="/internal/ai-worker/tasks/{task_id}/snapshot",
            llm_credentials_path_template="/internal/ai-worker/tasks/{task_id}/llm-credentials",
            worker_id="worker-local",
        )

        task = task_source.poll_task()

        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual("worker-task-1", task.task_id)
        self.assertIsNotNone(task.credential_error)
        self.assertIn("凭证接口不可用", task.credential_error)
        self.assertFalse(task.has_credentials)

    def test_poll_task_keeps_non_api_task_type_without_failing(self) -> None:
        class FunctionalTaskClient(FakePlatformHttpClient):
            def post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any] | None:
                payload = super().post(path, json_body)
                assert payload is not None
                payload["taskType"] = "functional_case_generate"
                return payload

            def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
                payload = super().get(path, params)
                assert payload is not None
                payload["run"]["taskType"] = "functional_case_generate"
                payload["run"]["sourceType"] = "text"
                payload["run"]["sourceContent"] = "功能测试需求文本"
                return payload

        task_source = HttpClaimTaskSource(
            client=FunctionalTaskClient(),
            claim_path="/internal/ai-worker/tasks/claim",
            snapshot_path_template="/internal/ai-worker/tasks/{task_id}/snapshot",
            llm_credentials_path_template="/internal/ai-worker/tasks/{task_id}/llm-credentials",
            worker_id="worker-local",
        )

        task = task_source.poll_task()

        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual("functional_case_generate", task.task_type)
        self.assertEqual("text", task.payload.source_type)
        self.assertEqual("功能测试需求文本", task.payload.source_content)

    def test_poll_ui_task_maps_source_archive_download_url(self) -> None:
        class UiTaskClient(FakePlatformHttpClient):
            def post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any] | None:
                payload = super().post(path, json_body)
                assert payload is not None
                payload["taskType"] = "ui_case_generate"
                return payload

            def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
                payload = super().get(path, params)
                assert payload is not None
                payload["run"]["taskType"] = "ui_case_generate"
                payload["run"]["sourceArchiveDownloadUrl"] = "/internal/tasks/source.zip"
                return payload

        task = HttpClaimTaskSource(
            client=UiTaskClient(),
            claim_path="/claim",
            snapshot_path_template="/snapshot/{task_id}",
            llm_credentials_path_template="/credentials/{task_id}",
            worker_id="worker",
        ).poll_task()

        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual("ui_case_generate", task.task_type)
        self.assertEqual("/internal/tasks/source.zip", task.payload.source_archive_download_url)

    def test_poll_functional_task_infers_source_type_from_document_type(self) -> None:
        class FunctionalDocumentTaskClient(FakePlatformHttpClient):
            def post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any] | None:
                payload = super().post(path, json_body)
                assert payload is not None
                payload["taskType"] = "functional_case_generate"
                return payload

            def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
                payload = super().get(path, params)
                assert payload is not None
                payload["run"]["taskType"] = "functional_case_generate"
                payload["run"].pop("sourceType", None)
                payload["run"]["documentType"] = "text"
                payload["run"]["sourceContent"] = "功能测试需求文本"
                return payload

        task_source = HttpClaimTaskSource(
            client=FunctionalDocumentTaskClient(),
            claim_path="/internal/ai-worker/tasks/claim",
            snapshot_path_template="/internal/ai-worker/tasks/{task_id}/snapshot",
            llm_credentials_path_template="/internal/ai-worker/tasks/{task_id}/llm-credentials",
            worker_id="worker-local",
        )

        task = task_source.poll_task()

        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual("functional_case_generate", task.task_type)
        self.assertEqual("text", task.payload.source_type)
        self.assertEqual("text", task.payload.document_type)
        self.assertEqual("功能测试需求文本", task.payload.source_content)

    def test_poll_task_maps_requirement_analysis_snapshot(self) -> None:
        class RequirementAnalysisTaskClient(FakePlatformHttpClient):
            def post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any] | None:
                self.claim_called = True
                self.last_claim_path = path
                self.last_claim_body = json_body
                return {
                    "id": "claim-lease-req-1",
                    "taskId": "worker-task-1",
                    "taskType": "requirement_analysis",
                    "runId": "run-1",
                    "generateTaskId": "task-1",
                    "projectId": "project-1",
                    "sprintId": "sprint-1",
                    "requirementId": "requirement-1",
                    "llmConnectionId": "llm-connection-1",
                    "checkpointEnabled": False,
                    "currentStage": "",
                    "leaseSeconds": 30,
                }

            def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
                self.snapshot_called = True
                self.last_snapshot_path = path
                return {
                    "taskType": "requirement_analysis",
                    "checkpointEnabled": False,
                    "currentStage": "",
                    "configJson": "{}",
                    "run": {
                        "taskId": "task-1",
                        "runId": "run-1",
                        "taskType": "requirement_analysis",
                        "name": "Login requirement analysis",
                        "projectId": "project-1",
                        "sprintId": "sprint-1",
                        "requirementId": "requirement-1",
                        "documentType": "word",
                        "documentDownloadUrl": "/internal/ai-worker/tasks/worker-task-1/requirement-document",
                        "instruction": "重点分析异常场景和歧义点",
                    },
                }

        client = RequirementAnalysisTaskClient()
        task_source = HttpClaimTaskSource(
            client=client,
            claim_path="/internal/ai-worker/tasks/claim",
            snapshot_path_template="/internal/ai-worker/tasks/{task_id}/snapshot",
            llm_credentials_path_template="/internal/ai-worker/tasks/{task_id}/llm-credentials",
            worker_id="worker-local",
        )

        task = task_source.poll_task()

        self.assertTrue(client.claim_called)
        self.assertTrue(client.snapshot_called)
        self.assertTrue(client.credentials_called)
        self.assertEqual(
            "/internal/ai-worker/tasks/worker-task-1/llm-credentials", client.last_credentials_path
        )
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual("claim-lease-req-1", task.claim_id)
        self.assertEqual("worker-task-1", task.task_id)
        self.assertEqual("run-1", task.run_id)
        self.assertEqual("task-1", task.generate_task_id)
        self.assertEqual("requirement_analysis", task.task_type)
        self.assertEqual("project-1", task.project_id)
        self.assertEqual("sprint-1", task.sprint_id)
        self.assertEqual("requirement-1", task.requirement_id)
        self.assertEqual("word", task.payload.source_type)
        self.assertEqual("word", task.payload.document_type)
        self.assertEqual("", task.payload.source_content)
        self.assertEqual(
            "/internal/ai-worker/tasks/worker-task-1/requirement-document",
            task.payload.document_download_url,
        )
        self.assertEqual("重点分析异常场景和歧义点", task.payload.extra_instruction)
        self.assertEqual("{}", task.config_json)

    def test_poll_task_infers_requirement_document_type_from_docx_source_type(self) -> None:
        class RequirementAnalysisDocxClient(FakePlatformHttpClient):
            def post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any] | None:
                payload = super().post(path, json_body)
                assert payload is not None
                payload["taskType"] = "requirement_analysis"
                payload["llmConnectionId"] = ""
                return payload

            def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
                return {
                    "taskType": "requirement_analysis",
                    "run": {
                        "taskId": "task-1",
                        "runId": "run-1",
                        "taskType": "requirement_analysis",
                        "name": "Docx requirement analysis",
                        "projectId": "project-1",
                        "sprintId": "sprint-1",
                        "requirementId": "requirement-1",
                        "sourceType": "docx",
                        "sourceContent": "",
                        "documentDownloadUrl": "/internal/ai-worker/tasks/worker-task-1/requirement-document",
                        "instruction": "",
                    },
                }

        task_source = HttpClaimTaskSource(
            client=RequirementAnalysisDocxClient(),
            claim_path="/internal/ai-worker/tasks/claim",
            snapshot_path_template="/internal/ai-worker/tasks/{task_id}/snapshot",
            llm_credentials_path_template="/internal/ai-worker/tasks/{task_id}/llm-credentials",
            worker_id="worker-local",
        )

        task = task_source.poll_task()

        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual("word", task.payload.source_type)
        self.assertEqual("word", task.payload.document_type)
        self.assertEqual("word", task.payload.metadata["documentType"])

    def test_poll_document_task_prefers_document_type_over_openapi_source_type(self) -> None:
        class ConflictingDocumentTypeClient(FakePlatformHttpClient):
            def post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any] | None:
                payload = super().post(path, json_body)
                assert payload is not None
                payload["taskType"] = "functional_case_generate"
                return payload

            def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
                payload = super().get(path, params)
                assert payload is not None
                payload["run"]["taskType"] = "functional_case_generate"
                payload["run"]["sourceType"] = "openapi"
                payload["run"]["documentType"] = "docx"
                payload["run"]["sourceContent"] = "功能测试需求文本"
                return payload

        task_source = HttpClaimTaskSource(
            client=ConflictingDocumentTypeClient(),
            claim_path="/internal/ai-worker/tasks/claim",
            snapshot_path_template="/internal/ai-worker/tasks/{task_id}/snapshot",
            llm_credentials_path_template="/internal/ai-worker/tasks/{task_id}/llm-credentials",
            worker_id="worker-local",
        )

        task = task_source.poll_task()

        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual("functional_case_generate", task.task_type)
        self.assertEqual("word", task.payload.document_type)
        self.assertEqual("word", task.payload.source_type)

    def test_poll_task_normalizes_requirement_document_type_docx_alias(self) -> None:
        class RequirementAnalysisDocxDocumentTypeClient(FakePlatformHttpClient):
            def post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any] | None:
                payload = super().post(path, json_body)
                assert payload is not None
                payload["taskType"] = "requirement_analysis"
                payload["llmConnectionId"] = ""
                return payload

            def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
                return {
                    "taskType": "requirement_analysis",
                    "run": {
                        "taskId": "task-1",
                        "runId": "run-1",
                        "taskType": "requirement_analysis",
                        "name": "Docx requirement analysis",
                        "projectId": "project-1",
                        "sprintId": "sprint-1",
                        "requirementId": "requirement-1",
                        "documentType": "docx",
                        "sourceContent": "",
                        "documentDownloadUrl": "/internal/ai-worker/tasks/worker-task-1/requirement-document",
                        "instruction": "",
                    },
                }

        task_source = HttpClaimTaskSource(
            client=RequirementAnalysisDocxDocumentTypeClient(),
            claim_path="/internal/ai-worker/tasks/claim",
            snapshot_path_template="/internal/ai-worker/tasks/{task_id}/snapshot",
            llm_credentials_path_template="/internal/ai-worker/tasks/{task_id}/llm-credentials",
            worker_id="worker-local",
        )

        task = task_source.poll_task()

        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual("word", task.payload.document_type)
        self.assertEqual("word", task.payload.metadata["documentType"])

    def test_task_service_and_poller_return_polled_task(self) -> None:
        client = FakePlatformHttpClient()
        task_source = HttpClaimTaskSource(
            client=client,
            claim_path="/internal/ai-worker/tasks/claim",
            snapshot_path_template="/internal/ai-worker/tasks/{task_id}/snapshot",
            llm_credentials_path_template="/internal/ai-worker/tasks/{task_id}/llm-credentials",
            worker_id="worker-local",
        )

        poller = TaskPoller(TaskService(task_source))
        task = poller.poll()

        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual("worker-task-1", task.task_id)


if __name__ == "__main__":
    unittest.main()
