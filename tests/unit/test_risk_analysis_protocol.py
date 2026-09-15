import sys
import unittest
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from testing_agent_ai_worker.config.models import Settings
from testing_agent_ai_worker.models.task import Task
from testing_agent_ai_worker.platform.task_source import (
    HttpClaimTaskSource,
    parse_gitlab_credentials,
)


def _snapshot_missing_new_fields() -> dict[str, Any]:
    return {
        "run": {
            "taskId": "worker-task-1",
            "runId": "run-1",
            "taskType": "api_case_generate",
            "name": "OpenAPI 用例生成",
            "projectId": "project-1",
            "sprintId": "sprint-1",
            "requirementId": "req-1",
            "sourceType": "openapi",
            "sourceContent": '{"openapi":"3.0.0"}',
            "instruction": "",
        }
    }


class FakePlatformHttpClient:
    def __init__(self, snapshot_payload: dict[str, Any]) -> None:
        self.timeout_seconds = 5.0
        self._snapshot_payload = snapshot_payload
        self.credentials_called = False

    def post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any] | None:
        return {
            "id": "claim-lease-1",
            "taskId": "worker-task-1",
            "runId": "run-1",
            "taskType": "code_risk_analysis",
            "projectId": "project-1",
            "sprintId": "sprint-1",
            "requirementId": "req-1",
            "leaseSeconds": 30,
            "llmConnectionId": "conn-1",
        }

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        return self._snapshot_payload

    def get_with_retry(
        self,
        path: str,
        max_retries: int = 3,
        backoff_base: float = 1.0,
    ) -> Any:
        self.credentials_called = True
        return {
            "baseUrl": "https://test-llm.example.com/v1",
            "modelId": "gpt-4o",
            "apiKey": "sk-test",
        }


def _risk_snapshot(*, fields_inside_run: bool = False) -> dict[str, Any]:
    base_run = {
        "taskId": "worker-task-1",
        "runId": "run-1",
        "taskType": "code_risk_analysis",
        "name": "登录需求风险分析",
        "projectId": "project-1",
        "sprintId": "sprint-1",
        "requirementId": "req-1",
        "instruction": "",
    }
    requirement = {
        "requirementId": "req-1",
        "name": "登录功能需求",
        "documentType": "text",
        "documentContent": "需求理解记录正文",
    }
    bindings = [
        {
            "bindingId": "binding-1",
            "repositoryId": "repo-1",
            "groupId": "group-1",
            "branch": "feat/login",
            "baselineBranch": "",
            "baselineRef": "refs/heads/master",
            "note": "",
            "error": "",
            "connectionId": "conn-gitlab-1",
        },
        {
            "bindingId": "binding-2",
            "repositoryId": "repo-2",
            "groupId": "group-1",
            "branch": "dev",
            "baselineBranch": "",
            "baselineRef": None,
            "note": "",
            "error": "基线分支已删除",
            "connectionId": "conn-gitlab-1",
        },
    ]
    existing_tests = {
        "functionCases": [
            {
                "suiteId": "f-suite-1",
                "suiteName": "登录功能",
                "caseId": "f-case-1",
                "title": "登录成功",
                "module": "登录",
                "preconditions": "已注册",
                "steps": "输入用户名密码",
                "expectedResults": "进入首页",
                "priority": "P1",
                "caseType": "function",
                "lastRun": None,
                "runNote": "功能用例暂无执行记录",
            }
        ],
        "apiCases": [
            {
                "collectionId": "a-col-1",
                "collectionName": "登录接口",
                "caseId": "a-case-1",
                "name": "登录成功返回 token",
                "description": "正例",
                "method": "POST",
                "urlTemplate": "/api/login",
                "assertRules": [
                    {
                        "name": "code=200",
                        "assertSource": "body",
                        "targetExpr": "code",
                        "comparator": "eq",
                        "expectedValue": 200,
                    }
                ],
                "lastRun": {"status": "passed", "finishedAt": "2026-08-20T10:00:00+08:00"},
            }
        ],
        "uiCases": [
            {
                "suiteId": "u-suite-1",
                "suiteName": "登录页面",
                "caseId": "u-case-1",
                "name": "登录按钮可见",
                "stepsJson": '[{"action":"click"}]',
                "lastRun": {"status": "failed", "finishedAt": "2026-08-21T10:00:00+08:00"},
            }
        ],
    }
    fields = {
        "requirement": requirement,
        "bindings": bindings,
        "existingTests": existing_tests,
        "gitlabCredentialsUrl": "/internal/ai-worker/tasks/worker-task-1/gitlab-credentials",
    }
    if fields_inside_run:
        return {"taskType": "code_risk_analysis", "run": {**base_run, **fields}}
    return {"taskType": "code_risk_analysis", "run": base_run, **fields}


class _PollingTestCase(unittest.TestCase):
    def _poll(self, snapshot_payload: dict[str, Any]) -> Task:
        task_source = HttpClaimTaskSource(
            client=FakePlatformHttpClient(snapshot_payload),
            claim_path="/internal/ai-worker/tasks/claim",
            snapshot_path_template="/internal/ai-worker/tasks/{task_id}/snapshot",
            llm_credentials_path_template="/internal/ai-worker/tasks/{task_id}/llm-credentials",
            worker_id="worker-local",
        )
        task = task_source.poll_task()
        assert task is not None
        return task


class RiskAnalysisSnapshotTests(_PollingTestCase):
    def test_poll_maps_requirement_bindings_existing_tests_and_credentials_url(self) -> None:
        task = self._poll(_risk_snapshot())

        self.assertEqual("code_risk_analysis", task.task_type)
        self.assertEqual("登录需求风险分析", task.name)

        requirement = task.requirement_input
        assert requirement is not None
        self.assertEqual("req-1", requirement.requirement_id)
        self.assertEqual("登录功能需求", requirement.name)
        self.assertEqual("text", requirement.document_type)
        self.assertEqual("需求理解记录正文", requirement.document_content)

        self.assertEqual(2, len(task.bindings))
        binding = task.bindings[0]
        self.assertEqual("binding-1", binding.binding_id)
        self.assertEqual("repo-1", binding.repository_id)
        self.assertEqual("group-1", binding.group_id)
        self.assertEqual("feat/login", binding.branch)
        self.assertEqual("refs/heads/master", binding.baseline_ref)
        self.assertEqual("conn-gitlab-1", binding.connection_id)
        self.assertEqual("基线分支已删除", task.bindings[1].error)
        self.assertIsNone(task.bindings[1].baseline_ref)

        existing = task.existing_tests
        function_case = existing.function_cases[0]
        self.assertEqual("f-case-1", function_case.case_id)
        self.assertIsNone(function_case.last_run)
        self.assertEqual("功能用例暂无执行记录", function_case.run_note)
        self.assertEqual("f-suite-1", function_case.suite_id)
        self.assertEqual("登录成功", function_case.title)
        self.assertEqual("P1", function_case.priority)

        api_case = existing.api_cases[0]
        self.assertEqual("a-case-1", api_case.case_id)
        self.assertEqual("登录接口", api_case.collection_name)
        self.assertEqual("POST", api_case.method)
        self.assertEqual(1, len(api_case.assert_rules))
        self.assertEqual("passed", api_case.last_run["status"])
        self.assertEqual("2026-08-20T10:00:00+08:00", api_case.last_run["finishedAt"])

        ui_case = existing.ui_cases[0]
        self.assertEqual("u-case-1", ui_case.case_id)
        self.assertEqual("failed", ui_case.last_run["status"])
        self.assertEqual("2026-08-21T10:00:00+08:00", ui_case.last_run["finishedAt"])

        self.assertEqual(
            "/internal/ai-worker/tasks/worker-task-1/gitlab-credentials",
            task.gitlab_credentials_url,
        )

    def test_poll_maps_risk_fields_placed_inside_run_for_backward_compatibility(self) -> None:
        task = self._poll(_risk_snapshot(fields_inside_run=True))

        assert task.requirement_input is not None
        self.assertEqual("需求理解记录正文", task.requirement_input.document_content)
        self.assertEqual(2, len(task.bindings))
        self.assertEqual("a-case-1", task.existing_tests.api_cases[0].case_id)
        self.assertEqual(
            "/internal/ai-worker/tasks/worker-task-1/gitlab-credentials",
            task.gitlab_credentials_url,
        )

    def test_poll_tolerates_snapshot_without_risk_analysis_fields(self) -> None:
        task = self._poll(_snapshot_missing_new_fields())

        self.assertEqual("api_case_generate", task.task_type)
        self.assertIsNone(task.requirement_input)
        self.assertEqual([], task.bindings)
        self.assertEqual([], task.existing_tests.function_cases)
        self.assertEqual("", task.gitlab_credentials_url)

    def test_poll_tolerates_snake_case_fields_and_unknown_extras(self) -> None:
        payload = _risk_snapshot()
        payload["existing_tests"] = payload.pop("existingTests")
        payload["gitlab_credentials_url"] = payload.pop("gitlabCredentialsUrl")
        payload["requirement"]["futureMeta"] = {"x": 1}
        payload["bindings"][0] = {
            "binding_id": "binding-1",
            "repository_id": "repo-1",
            "group_id": "group-1",
            "branch": "feat/login",
            "baseline_branch": "",
            "baseline_ref": "refs/heads/master",
            "note": "",
            "error": "",
            "connection_id": "conn-gitlab-1",
            "unexpectedField": "keep-me",
        }
        payload["run"]["futureField"] = "ignored"

        task = self._poll(payload)

        assert task.requirement_input is not None
        self.assertEqual("需求理解记录正文", task.requirement_input.document_content)
        self.assertEqual("refs/heads/master", task.bindings[0].baseline_ref)
        self.assertEqual("conn-gitlab-1", task.bindings[0].connection_id)
        self.assertEqual("a-case-1", task.existing_tests.api_cases[0].case_id)
        self.assertEqual(
            "/internal/ai-worker/tasks/worker-task-1/gitlab-credentials",
            task.gitlab_credentials_url,
        )


class GitlabCredentialsParsingTests(unittest.TestCase):
    def test_parse_gitlab_credentials_aggregates_repeated_connection_ids(self) -> None:
        payload = {
            "taskId": "worker-task-1",
            "bindings": [],
            "credentials": [
                {
                    "connectionId": "conn-1",
                    "baseUrl": "https://gitlab.example.com",
                    "accessToken": "token-1",
                    "repositoryIds": ["repo-1"],
                },
                {
                    "connectionId": "conn-1",
                    "baseUrl": "https://gitlab.example.com",
                    "accessToken": "token-1",
                    "repositoryIds": ["repo-2"],
                },
                {
                    "connectionId": "conn-2",
                    "baseUrl": "https://gitlab.example.com",
                    "accessToken": "token-2",
                    "repositoryIds": ["repo-3"],
                },
            ],
        }

        credentials = parse_gitlab_credentials(payload)

        self.assertEqual(2, len(credentials))
        first = next(c for c in credentials if c.connection_id == "conn-1")
        self.assertEqual("token-1", first.access_token)
        self.assertEqual(["repo-1", "repo-2"], sorted(first.repository_ids))
        second = next(c for c in credentials if c.connection_id == "conn-2")
        self.assertEqual(["repo-3"], second.repository_ids)

    def test_parse_gitlab_credentials_never_merges_missing_connection_ids(self) -> None:
        payload = {
            "taskId": "worker-task-1",
            "credentials": [
                {
                    "connectionId": "",
                    "baseUrl": "https://gitlab.example.com",
                    "accessToken": "token-a",
                    "repositoryIds": ["repo-1"],
                },
                {
                    "connectionId": "",
                    "baseUrl": "https://gitlab.example.com",
                    "accessToken": "token-b",
                    "repositoryIds": ["repo-2"],
                },
            ],
        }

        credentials = parse_gitlab_credentials(payload)

        self.assertEqual(2, len(credentials))
        self.assertEqual({"token-a", "token-b"}, {c.access_token for c in credentials})

    def test_parse_gitlab_credentials_tolerates_missing_payload(self) -> None:
        self.assertEqual([], parse_gitlab_credentials({}))
        self.assertEqual([], parse_gitlab_credentials({"credentials": None}))


class CodeRiskAnalysisConfigTests(unittest.TestCase):
    def test_gitlab_timeout_seconds_defaults_to_120(self) -> None:
        settings = Settings()

        self.assertEqual(120.0, settings.code_risk_analysis.gitlab_timeout_seconds)

    def test_gitlab_timeout_seconds_overridable_via_toml(self) -> None:
        import tempfile

        from testing_agent_ai_worker.config.loader import load_settings

        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("[code_risk_analysis]\ngitlab_timeout_seconds = 45\n")
            config_path = f.name
        try:
            settings = load_settings(config_path)
        finally:
            Path(config_path).unlink(missing_ok=True)

        self.assertEqual(45.0, settings.code_risk_analysis.gitlab_timeout_seconds)


if __name__ == "__main__":
    unittest.main()
