"""Code risk analysis executor: orchestrate GitLab diff fetch, prompt assembly and report submission."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import yaml

from testing_agent_ai_worker.config.models import NanobotConfig
from testing_agent_ai_worker.models.execution import TaskProgress, TaskResult, TaskStatus
from testing_agent_ai_worker.models.task import GitlabCredentials, Task
from testing_agent_ai_worker.nanobot_runtime.config_builder import task_config_path
from testing_agent_ai_worker.nanobot_runtime.paths import (
    resolve_runtime_paths,
    resolve_task_workspace,
)
from testing_agent_ai_worker.platform.http_client import PlatformHttpClient
from testing_agent_ai_worker.platform.task_source import parse_gitlab_credentials
from testing_agent_ai_worker.tasks.code_risk_analysis.gitlab_diffs import fetch_repo_diffs
from testing_agent_ai_worker.tasks.functional_case_generate.chain import run_skill_step
from testing_agent_ai_worker.tasks.result_summary import build_task_result_summary
from testing_agent_ai_worker.worker.runner import TaskExecutor

CODE_RISK_SKILL_NAME = "code-risk-analysis"


class ReportInvalidError(ValueError):
    """风险分析输出未通过轻校验。"""


def validate_risk_report_yaml(text: str) -> str:
    """轻校验:非空 + 剥掉代码块围栏后可解析为顶层 YAML map。

    通过后返回原文(原文无围栏时原样透传,含围栏时剥围栏后透传),不做深度字段校验。
    """

    stripped = text.strip()
    if not stripped:
        raise ReportInvalidError("风险分析结果为空")
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if not lines[-1].strip().startswith("```"):
            raise ReportInvalidError("风险分析结果不是有效 YAML 对象(代码块围栏未闭合)")
        stripped = "\n".join(lines[1:-1]).strip()
    try:
        parsed = yaml.safe_load(stripped)
    except yaml.YAMLError as exc:
        raise ReportInvalidError(f"风险分析结果不是有效 YAML: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ReportInvalidError("风险分析结果不是有效 YAML 对象")
    return stripped


def _default_skill_dir_checker(workspace: Path, skill_name: str) -> bool:
    """检查部署侧预置的技能目录是否就位(ADR 0002)。"""

    return (workspace / "skills" / skill_name).exists()


def _platform_credentials_fetcher(client: PlatformHttpClient):
    def _fetch(task: Task) -> list[GitlabCredentials]:
        url = task.gitlab_credentials_url
        if not url:
            raise RuntimeError("快照缺少 gitlabCredentialsUrl")
        payload = client.get(url)
        return parse_gitlab_credentials(payload)

    return _fetch


class CodeRiskAnalysisNanobotExecutor(TaskExecutor):
    """代码风险分析执行器:单次执行,无 checkpoint/分片,凭据仅驻内存。"""

    def __init__(
        self,
        *,
        nanobot_config: NanobotConfig,
        skill_runner: Callable[..., Any] = run_skill_step,
        skill_name: str = CODE_RISK_SKILL_NAME,
        credentials_fetcher: Callable[[Task], list[GitlabCredentials]] | None = None,
        diff_fetcher: Callable[..., list[Any]] | None = None,
        skill_dir_checker: Callable[[Path, str], bool] | None = None,
        client: PlatformHttpClient | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.nanobot_config = nanobot_config
        self.runtime_paths = resolve_runtime_paths(nanobot_config)
        self.skill_runner = skill_runner
        self.skill_name = skill_name
        self.credentials_fetcher = credentials_fetcher or (
            _platform_credentials_fetcher(client) if client is not None else None
        )
        self.diff_fetcher = diff_fetcher or fetch_repo_diffs
        self.skill_dir_checker = skill_dir_checker or _default_skill_dir_checker
        self.timeout_seconds = timeout_seconds

    def execute(self, task: Task, started_at: datetime, progress_callback) -> TaskResult:
        if task.task_type != "code_risk_analysis":
            return self._failed_result(
                task,
                started_at,
                f"不支持的任务类型: {task.task_type}",
            )

        # 前置检查:需求理解记录、凭据、技能包 —— 失败不报任何进度。
        requirement = task.requirement_input
        if requirement is None or not requirement.document_content.strip():
            return self._failed_result(
                task,
                started_at,
                "该需求尚未完成需求分析(快照缺少需求理解记录)",
                remediation="先对需求发起 requirement_analysis",
            )
        if self.credentials_fetcher is None:
            return self._failed_result(
                task,
                started_at,
                "worker 未配置 GitLab 凭据获取",
                remediation="检查 worker 配置或重新绑定",
            )
        try:
            credentials = self.credentials_fetcher(task)
        except Exception as exc:
            return self._failed_result(
                task,
                started_at,
                f"GitLab 凭据不可用: {exc}",
                remediation="检查 GitLab PAT 或重新绑定",
            )

        workspace = resolve_task_workspace(self.nanobot_config, task)
        if not self.skill_dir_checker(workspace, self.skill_name):
            return self._failed_result(
                task,
                started_at,
                "项目技能包未预置(缺少 code-risk-analysis)",
                remediation="由部署侧按项目预置技能包后重新发起",
            )

        progress_callback(
            TaskProgress(
                task_id=task.task_id,
                run_id=task.run_id,
                current_stage="fetching_diff",
                stage_status="running",
            )
        )
        try:
            repo_diffs = self.diff_fetcher(
                bindings=task.bindings,
                credentials=credentials,
                timeout_seconds=self.timeout_seconds,
            )
        except Exception as exc:
            return self._failed_result(
                task,
                started_at,
                str(exc),
                remediation="手工指定基线 / 重新绑定 / 检查 PAT",
            )

        progress_callback(
            TaskProgress(
                task_id=task.task_id,
                run_id=task.run_id,
                current_stage="analyzing",
                stage_status="running",
            )
        )
        input_text = self._build_input_text(task, list(repo_diffs))
        with task_config_path(nanobot_config=self.nanobot_config, task=task) as config_path:
            raw_report = self._resolve_runner_result(
                self.skill_runner(
                    input_text=input_text,
                    session_key=task.nanobot_session_key,
                    skill_name=self.skill_name,
                    config_path=config_path,
                    workspace=str(workspace),
                    extra_instruction=task.payload.extra_instruction,
                )
            )
        try:
            report_text = validate_risk_report_yaml(raw_report)
        except ReportInvalidError as exc:
            return self._failed_result(
                task,
                started_at,
                str(exc),
                remediation="重新发起风险分析(报告格式异常)",
            )

        return TaskResult(
            task_id=task.task_id,
            run_id=task.run_id,
            generate_task_id=task.generate_task_id,
            status=TaskStatus.SUCCESS,
            output_yaml=report_text,
            result_summary_json=build_task_result_summary(
                task=task,
                status=TaskStatus.SUCCESS,
                error_message=None,
                details={
                    "repositoryCount": len(repo_diffs),
                    "filesChangedTotal": sum(r.files_changed for r in repo_diffs),
                    "riskReportLength": len(report_text),
                },
            ),
            started_at=started_at,
            finished_at=datetime.now().astimezone(),
        )

    @staticmethod
    def _resolve_runner_result(result) -> str:
        if hasattr(result, "__await__"):
            resolved = asyncio.run(result)
        else:
            resolved = result
        if not isinstance(resolved, str):
            raise ValueError("风险分析技能结果必须是文本")
        return resolved

    @staticmethod
    def _build_input_text(task: Task, repo_diffs: list[Any]) -> str:
        parts: list[str] = ["# 需求理解记录"]
        if task.requirement_input is not None:
            parts.append(task.requirement_input.document_content)

        for repo_diff in repo_diffs:
            parts.append(f"# 仓库 {repo_diff.repository_id}(分支 {repo_diff.branch})")
            parts.append(
                f"基线 commit: {repo_diff.baseline_commit};HEAD commit: {repo_diff.head_commit}"
            )
            parts.append(
                f"变更统计: {repo_diff.files_changed} 个文件,+{repo_diff.additions} -{repo_diff.deletions}"
            )
            for diff_file in repo_diff.diff_files:
                path = diff_file.get("new_path") or diff_file.get("old_path") or ""
                parts.append(f"diff --git a/{path} b/{path}")
                parts.append(diff_file.get("diff") or "")

        existing = task.existing_tests
        parts.append("# 现有测试内容")
        parts.append("## 功能用例")
        for case in existing.function_cases:
            parts.append(
                f"- 用例: {case.title}({case.case_id}) 套件: {case.suite_name} "
                f"优先级: {case.priority};执行记录: {case.run_note}"
            )
            parts.append(f"  步骤: {case.steps};预期结果: {case.expected_results}")
        parts.append("## API 用例")
        for case in existing.api_cases:
            last_run = case.last_run or {}
            parts.append(
                f"- 用例: {case.name}({case.case_id}) 集合: {case.collection_name} "
                f"方法: {case.method} URL: {case.url_template};"
                f"最近运行: {last_run.get('status', '无')} / {last_run.get('finishedAt', '无')}"
            )
            parts.append(
                f"  断言规则: {json.dumps(case.assert_rules, ensure_ascii=False, default=str)}"
            )
        parts.append("## UI 用例")
        for case in existing.ui_cases:
            last_run = case.last_run or {}
            parts.append(
                f"- 用例: {case.name}({case.case_id}) 套件: {case.suite_name};"
                f"最近运行: {last_run.get('status', '无')} / {last_run.get('finishedAt', '无')}"
            )
            parts.append(f"  步骤: {case.steps_json}")
        return "\n\n".join(parts)

    def _failed_result(
        self,
        task: Task,
        started_at: datetime,
        message: str,
        remediation: str | None = None,
    ) -> TaskResult:
        return TaskResult(
            task_id=task.task_id,
            run_id=task.run_id,
            generate_task_id=task.generate_task_id,
            status=TaskStatus.FAILED,
            error_message=message,
            remediation=remediation,
            result_summary_json=build_task_result_summary(
                task=task,
                status=TaskStatus.FAILED,
                error_message=message,
                details={"remediation": remediation} if remediation else None,
            ),
            started_at=started_at,
            finished_at=datetime.now().astimezone(),
        )
