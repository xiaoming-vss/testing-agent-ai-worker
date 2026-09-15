"""Core task models for the worker polling layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


@dataclass(slots=True)
class LlmCredentials:
    model: str
    api_key: str
    base_url: str


@dataclass(slots=True)
class GitlabCredentials:
    connection_id: str
    base_url: str
    access_token: str
    repository_ids: list[str]


class RequirementInput(BaseModel):
    """代码风险分析的需求输入:需求分析任务产出的需求理解记录。"""

    model_config = ConfigDict(extra="allow")

    requirement_id: str = Field(
        default="",
        validation_alias=AliasChoices("requirementId", "requirement_id"),
    )
    name: str = ""
    document_type: str = Field(
        default="",
        validation_alias=AliasChoices("documentType", "document_type"),
    )
    document_content: str = Field(
        default="",
        validation_alias=AliasChoices("documentContent", "document_content"),
    )


class RepositoryBinding(BaseModel):
    """需求与(仓库 + 分支)的代码绑定,含控制面的基线解析结果。"""

    model_config = ConfigDict(extra="allow")

    binding_id: str = Field(default="", validation_alias=AliasChoices("bindingId", "binding_id"))
    repository_id: str = Field(
        default="",
        validation_alias=AliasChoices("repositoryId", "repository_id"),
    )
    group_id: str = Field(default="", validation_alias=AliasChoices("groupId", "group_id"))
    branch: str = ""
    baseline_branch: str = Field(
        default="",
        validation_alias=AliasChoices("baselineBranch", "baseline_branch"),
    )
    baseline_ref: str | None = Field(
        default=None,
        validation_alias=AliasChoices("baselineRef", "baseline_ref"),
    )
    note: str = ""
    error: str = ""
    connection_id: str = Field(
        default="",
        validation_alias=AliasChoices("connectionId", "connection_id"),
    )


class FunctionCaseInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    suite_id: str = Field(default="", validation_alias=AliasChoices("suiteId", "suite_id"))
    suite_name: str = Field(default="", validation_alias=AliasChoices("suiteName", "suite_name"))
    case_id: str = Field(default="", validation_alias=AliasChoices("caseId", "case_id"))
    title: str = ""
    module: str = ""
    preconditions: str = ""
    steps: Any | None = None
    expected_results: Any | None = Field(
        default=None,
        validation_alias=AliasChoices("expectedResults", "expected_results"),
    )
    priority: str = ""
    case_type: str = Field(default="", validation_alias=AliasChoices("caseType", "case_type"))
    last_run: dict[str, object] | None = Field(
        default=None,
        validation_alias=AliasChoices("lastRun", "last_run"),
    )
    run_note: str = Field(
        default="功能用例暂无执行记录",
        validation_alias=AliasChoices("runNote", "run_note"),
    )


class ApiCaseInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    collection_id: str = Field(
        default="",
        validation_alias=AliasChoices("collectionId", "collection_id"),
    )
    collection_name: str = Field(
        default="",
        validation_alias=AliasChoices("collectionName", "collection_name"),
    )
    case_id: str = Field(default="", validation_alias=AliasChoices("caseId", "case_id"))
    name: str = ""
    description: str = ""
    method: str = ""
    url_template: str = Field(
        default="",
        validation_alias=AliasChoices("urlTemplate", "url_template"),
    )
    assert_rules: list[dict[str, object]] = Field(
        default_factory=list,
        validation_alias=AliasChoices("assertRules", "assert_rules"),
    )
    last_run: dict[str, object] | None = Field(
        default=None,
        validation_alias=AliasChoices("lastRun", "last_run"),
    )


class UiCaseInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    suite_id: str = Field(default="", validation_alias=AliasChoices("suiteId", "suite_id"))
    suite_name: str = Field(default="", validation_alias=AliasChoices("suiteName", "suite_name"))
    case_id: str = Field(default="", validation_alias=AliasChoices("caseId", "case_id"))
    name: str = ""
    steps_json: Any | None = Field(
        default=None,
        validation_alias=AliasChoices("stepsJson", "steps_json"),
    )
    last_run: dict[str, object] | None = Field(
        default=None,
        validation_alias=AliasChoices("lastRun", "last_run"),
    )


class ExistingTestCases(BaseModel):
    """该需求下现有测试内容:功能/API/UI 用例全量定义与最近一次执行状态。"""

    model_config = ConfigDict(extra="allow")

    function_cases: list[FunctionCaseInfo] = Field(
        default_factory=list,
        validation_alias=AliasChoices("functionCases", "function_cases"),
    )
    api_cases: list[ApiCaseInfo] = Field(
        default_factory=list,
        validation_alias=AliasChoices("apiCases", "api_cases"),
    )
    ui_cases: list[UiCaseInfo] = Field(
        default_factory=list,
        validation_alias=AliasChoices("uiCases", "ui_cases"),
    )


class TaskPayload(BaseModel):
    openapi_content: str
    source_content: str = ""
    document_download_url: str = ""
    source_archive_download_url: str = ""
    document_type: str = ""
    source_type: str = ""
    target_scope: str = ""
    extra_instruction: str = ""
    daily_metrics: dict[str, Any] = Field(default_factory=dict)
    llm_credentials: LlmCredentials | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Task(BaseModel):
    claim_id: str = ""
    task_id: str
    run_id: str = ""
    generate_task_id: str = ""
    task_type: str = "api_case_generate"
    name: str = ""
    project_id: str = ""
    sprint_id: str = ""
    requirement_id: str = ""
    lease_seconds: int = 30
    checkpoint_enabled: bool = False
    current_stage: str = ""
    config_json: str = ""
    payload: TaskPayload
    credential_error: str | None = None
    requirement_input: RequirementInput | None = None
    bindings: list[RepositoryBinding] = Field(default_factory=list)
    existing_tests: ExistingTestCases = Field(default_factory=ExistingTestCases)
    gitlab_credentials_url: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def has_credentials(self) -> bool:
        return self.payload.llm_credentials is not None

    @property
    def nanobot_session_key(self) -> str:
        return self.run_id.strip()
