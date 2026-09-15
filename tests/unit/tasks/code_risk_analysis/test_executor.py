import sys
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from testing_agent_ai_worker.config.models import NanobotConfig
from testing_agent_ai_worker.models.execution import TaskStatus
from testing_agent_ai_worker.models.task import (
    ExistingTestCases,
    GitlabCredentials,
    RepositoryBinding,
    RequirementInput,
    Task,
    TaskPayload,
)
from testing_agent_ai_worker.tasks.code_risk_analysis.executor import (
    CODE_RISK_SKILL_NAME,
    CodeRiskAnalysisNanobotExecutor,
)
from testing_agent_ai_worker.tasks.code_risk_analysis.gitlab_diffs import (
    GitlabDiffError,
    GitlabRepoDiff,
)


def _task(
    *,
    requirement: RequirementInput | None = None,
    bindings: list[RepositoryBinding] | None = None,
    existing_tests: ExistingTestCases | None = None,
) -> Task:
    if requirement is None:
        requirement = RequirementInput.model_validate(
            {
                "requirementId": "req-1",
                "name": "登录功能需求",
                "documentType": "text",
                "documentContent": "需求理解记录正文",
            }
        )
    return Task(
        task_id="task-1",
        run_id="run-1",
        generate_task_id="generate-1",
        task_type="code_risk_analysis",
        project_id="project-1",
        sprint_id="sprint-1",
        requirement_id="req-1",
        requirement_input=requirement,
        bindings=bindings
        or [
            RepositoryBinding.model_validate(
                {
                    "bindingId": "b-1",
                    "repositoryId": "repo-1",
                    "branch": "feat/login",
                    "baselineRef": "refs/heads/master",
                    "connectionId": "conn-1",
                }
            )
        ],
        existing_tests=existing_tests or ExistingTestCases(),
        gitlab_credentials_url="/internal/ai-worker/tasks/task-1/gitlab-credentials",
        payload=TaskPayload(openapi_content="", extra_instruction=""),
    )


def _existing_tests() -> ExistingTestCases:
    return ExistingTestCases.model_validate(
        {
            "functionCases": [
                {
                    "suiteId": "f-suite-1",
                    "suiteName": "登录功能",
                    "caseId": "f-case-1",
                    "title": "登录成功",
                    "steps": "输入用户名密码",
                    "expectedResults": "进入首页",
                    "priority": "P1",
                    "lastRun": None,
                }
            ],
            "apiCases": [
                {
                    "collectionId": "a-col-1",
                    "collectionName": "登录接口",
                    "caseId": "a-case-1",
                    "name": "登录成功返回 token",
                    "method": "POST",
                    "urlTemplate": "/api/login",
                    "assertRules": [
                        {"name": "code=200", "targetExpr": "code", "expectedValue": 200}
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
    )


def _repo_diff() -> GitlabRepoDiff:
    return GitlabRepoDiff(
        repository_id="repo-1",
        branch="feat/login",
        baseline_commit="abc123",
        head_commit="def456",
        files_changed=1,
        additions=1,
        deletions=1,
        diff_files=[
            {"old_path": "src/a.py", "new_path": "src/a.py", "diff": "@@ -1 +1 @@\n-x\n+y\n"}
        ],
    )


class _RecordingSkillRunner:
    def __init__(self, output: str = "analyzedAt: '2026-08-27T10:00:00+08:00'\nrisks: []") -> None:
        self.output = output
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.output


class _FakeCredentialsFetcher:
    def __init__(self, *, token: str = "secret-token-1", fail: bool = False) -> None:
        self.token = token
        self.fail = fail
        self.calls = 0

    def __call__(self, task: Task) -> list[GitlabCredentials]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("凭证接口不可用")
        return [
            GitlabCredentials(
                connection_id="conn-1",
                base_url="https://gitlab.example.com",
                access_token=self.token,
                repository_ids=["repo-1"],
            )
        ]


class _FakeDiffFetcher:
    def __init__(
        self, *, results: list[GitlabRepoDiff] | None = None, fail: GitlabDiffError | None = None
    ) -> None:
        self.results = results or [_repo_diff()]
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail is not None:
            raise self.fail
        return self.results


class CodeRiskAnalysisExecutorTests(unittest.TestCase):
    def _executor(
        self,
        *,
        skill_runner: _RecordingSkillRunner,
        fetcher: _FakeCredentialsFetcher | None = None,
        diff_fetcher: _FakeDiffFetcher | None = None,
        skill_checker=None,
    ) -> CodeRiskAnalysisNanobotExecutor:
        # 单测环境无实际 skills 目录,默认视为技能包存在;专门测缺失场景时传 False。
        if skill_checker is None:

            def skill_checker(_workspace, _name):
                return True

        return CodeRiskAnalysisNanobotExecutor(
            nanobot_config=NanobotConfig(runtime_root=str(Path("runtime/code-risk-analysis"))),
            skill_runner=skill_runner,
            credentials_fetcher=fetcher or _FakeCredentialsFetcher(),
            diff_fetcher=diff_fetcher or _FakeDiffFetcher(),
            skill_dir_checker=skill_checker,
        )

    def test_execute_success_passes_three_section_input_and_reports_stages(self) -> None:
        skill_runner = _RecordingSkillRunner()
        executor = self._executor(skill_runner=skill_runner)
        progresses = []

        result = executor.execute(
            _task(existing_tests=_existing_tests()), datetime.now().astimezone(), progresses.append
        )

        self.assertEqual(TaskStatus.SUCCESS, result.status)
        self.assertEqual(2, len(progresses))
        self.assertEqual(["fetching_diff", "analyzing"], [p.current_stage for p in progresses])
        self.assertEqual(["running", "running"], [p.stage_status for p in progresses])
        self.assertEqual(1, len(skill_runner.calls))
        call = skill_runner.calls[0]
        self.assertEqual(CODE_RISK_SKILL_NAME, call["skill_name"])
        input_text = str(call["input_text"])
        self.assertIn("需求理解记录正文", input_text)
        self.assertIn("repo-1", input_text)
        self.assertIn("feat/login", input_text)
        self.assertIn("abc123", input_text)
        self.assertIn("def456", input_text)
        self.assertIn("src/a.py", input_text)
        self.assertIn("登录成功", input_text)
        self.assertIn("功能用例暂无执行记录", input_text)
        self.assertIn("登录成功返回 token", input_text)
        self.assertIn("passed", input_text)
        self.assertIn("登录按钮可见", input_text)
        self.assertEqual(skill_runner.output, result.output_yaml)
        summary = result.result_summary_json
        self.assertIn('"taskType": "code_risk_analysis"', summary)
        self.assertIn('"repositoryCount": 1', summary)

    def test_execute_fails_when_requirement_understanding_record_missing(self) -> None:
        skill_runner = _RecordingSkillRunner()
        executor = self._executor(skill_runner=skill_runner)
        progresses = []
        task = _task()
        task.requirement_input = None

        result = executor.execute(task, datetime.now().astimezone(), progresses.append)

        self.assertEqual(TaskStatus.FAILED, result.status)
        self.assertIn("尚未完成需求分析", result.error_message or "")
        self.assertIn("requirement_analysis", result.remediation or "")
        self.assertEqual([], progresses)
        self.assertEqual([], skill_runner.calls)

    def test_execute_fails_when_credentials_unavailable_before_progress(self) -> None:
        skill_runner = _RecordingSkillRunner()
        executor = self._executor(
            skill_runner=skill_runner, fetcher=_FakeCredentialsFetcher(fail=True)
        )
        progresses = []

        result = executor.execute(_task(), datetime.now().astimezone(), progresses.append)

        self.assertEqual(TaskStatus.FAILED, result.status)
        self.assertIn("凭证接口不可用", result.error_message or "")
        self.assertIn("PAT", result.remediation or "")
        self.assertEqual([], progresses)
        self.assertEqual([], skill_runner.calls)

    def test_execute_fails_when_skill_package_missing(self) -> None:
        skill_runner = _RecordingSkillRunner()
        executor = self._executor(
            skill_runner=skill_runner, skill_checker=lambda _workspace, _name: False
        )
        progresses = []

        result = executor.execute(_task(), datetime.now().astimezone(), progresses.append)

        self.assertEqual(TaskStatus.FAILED, result.status)
        self.assertIn("项目技能包未预置", result.error_message or "")
        self.assertIn("预置", result.remediation or "")
        self.assertEqual([], progresses)
        self.assertEqual([], skill_runner.calls)

    def test_execute_fails_when_repo_diff_fails_and_reports_fetching_progress(self) -> None:
        skill_runner = _RecordingSkillRunner()
        executor = self._executor(
            skill_runner=skill_runner,
            diff_fetcher=_FakeDiffFetcher(
                fail=GitlabDiffError("仓库 repo-2 基线解析失败: 已删除(请手工指定基线)")
            ),
        )
        progresses = []

        result = executor.execute(_task(), datetime.now().astimezone(), progresses.append)

        self.assertEqual(TaskStatus.FAILED, result.status)
        self.assertIn("repo-2", result.error_message or "")
        self.assertIn("基线", result.remediation or "")
        self.assertEqual(["fetching_diff"], [p.current_stage for p in progresses])
        self.assertEqual([], skill_runner.calls)

    def test_execute_fails_when_report_is_empty(self) -> None:
        skill_runner = _RecordingSkillRunner(output="")
        executor = self._executor(skill_runner=skill_runner)

        result = executor.execute(_task(), datetime.now().astimezone(), lambda _p: None)

        self.assertEqual(TaskStatus.FAILED, result.status)
        self.assertIn("为空", result.error_message or "")

    def test_execute_fails_when_report_is_not_a_mapping(self) -> None:
        skill_runner = _RecordingSkillRunner(output="- a\n- b\n")
        executor = self._executor(skill_runner=skill_runner)

        result = executor.execute(_task(), datetime.now().astimezone(), lambda _p: None)

        self.assertEqual(TaskStatus.FAILED, result.status)
        self.assertIn("不是有效 YAML 对象", result.error_message or "")

    def test_execute_strips_yaml_fence_before_validation_and_passes_text_through(self) -> None:
        skill_runner = _RecordingSkillRunner(
            output="```yaml\nanalyzedAt: '2026-08-27T10:00:00+08:00'\nrisks: []\n```"
        )
        executor = self._executor(skill_runner=skill_runner)

        result = executor.execute(_task(), datetime.now().astimezone(), lambda _p: None)

        self.assertEqual(TaskStatus.SUCCESS, result.status)
        self.assertEqual("analyzedAt: '2026-08-27T10:00:00+08:00'\nrisks: []", result.output_yaml)

    def test_execute_never_leaks_access_token_into_input_output_or_summary(self) -> None:
        skill_runner = _RecordingSkillRunner()
        executor = self._executor(
            skill_runner=skill_runner, fetcher=_FakeCredentialsFetcher(token="secret-token-1")
        )
        progresses = []

        result = executor.execute(
            _task(existing_tests=_existing_tests()), datetime.now().astimezone(), progresses.append
        )

        self.assertEqual(TaskStatus.SUCCESS, result.status)
        produced_texts = [
            str(skill_runner.calls[0]["input_text"]),
            result.output_yaml,
            result.result_summary_json,
            result.intermediate_json_text,
        ]
        produced_texts += [str(p) for p in progresses]
        self.assertNotIn("secret-token-1", "".join(produced_texts))

    def test_execute_rejects_other_task_types(self) -> None:
        skill_runner = _RecordingSkillRunner()
        executor = self._executor(skill_runner=skill_runner)
        task = _task()
        task.task_type = "test_report_generate"

        result = executor.execute(task, datetime.now().astimezone(), lambda _p: None)

        self.assertEqual(TaskStatus.FAILED, result.status)
        self.assertIn("不支持的任务类型", result.error_message or "")


if __name__ == "__main__":
    unittest.main()
