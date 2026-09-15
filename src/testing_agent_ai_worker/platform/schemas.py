"""Platform protocol response models for claim/snapshot/llm-credentials."""

from __future__ import annotations

from pydantic import AliasChoices, BaseModel, Field


class PlatformClaimTask(BaseModel):
    claim_id: str = Field(
        default="",
        validation_alias=AliasChoices("id", "claimId", "claim_id", "leaseId", "lease_id"),
    )
    task_id: str = Field(validation_alias=AliasChoices("taskId", "task_id", "id"))
    run_id: str = Field(default="", validation_alias=AliasChoices("runId", "run_id"))
    generate_task_id: str = Field(
        default="",
        validation_alias=AliasChoices("generateTaskId", "generate_task_id"),
    )
    task_type: str = Field(
        default="api_case_generate",
        validation_alias=AliasChoices("taskType", "task_type", "type"),
    )
    project_id: str = Field(default="", validation_alias=AliasChoices("projectId", "project_id"))
    sprint_id: str = Field(default="", validation_alias=AliasChoices("sprintId", "sprint_id"))
    requirement_id: str = Field(
        default="",
        validation_alias=AliasChoices("requirementId", "requirement_id"),
    )
    lease_seconds: int = Field(
        default=30,
        validation_alias=AliasChoices("leaseSeconds", "lease_seconds"),
    )
    llm_connection_id: str = Field(
        default="",
        validation_alias=AliasChoices("llmConnectionId", "llm_connection_id"),
    )
    checkpoint_enabled: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("checkpointEnabled", "checkpoint_enabled"),
    )
    current_stage: str = Field(
        default="",
        validation_alias=AliasChoices("currentStage", "current_stage"),
    )
    config_json: str = Field(
        default="",
        validation_alias=AliasChoices("configJson", "config_json"),
    )
    daily_metrics: dict[str, object] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("dailyMetrics", "daily_metrics"),
    )


class PlatformLlmCredentials(BaseModel):
    base_url: str = Field(validation_alias=AliasChoices("baseUrl", "base_url"))
    model_id: str = Field(validation_alias=AliasChoices("modelId", "model_id"))
    api_key: str = Field(validation_alias=AliasChoices("apiKey", "api_key"))


class PlatformSnapshotRun(BaseModel):
    task_id: str = Field(validation_alias=AliasChoices("taskId", "task_id", "id"))
    run_id: str = Field(default="", validation_alias=AliasChoices("runId", "run_id"))
    generate_task_id: str = Field(
        default="",
        validation_alias=AliasChoices("generateTaskId", "generate_task_id"),
    )
    task_type: str = Field(
        default="api_case_generate",
        validation_alias=AliasChoices("taskType", "task_type", "type"),
    )
    name: str = ""
    project_id: str = Field(default="", validation_alias=AliasChoices("projectId", "project_id"))
    sprint_id: str = Field(default="", validation_alias=AliasChoices("sprintId", "sprint_id"))
    requirement_id: str = Field(
        default="",
        validation_alias=AliasChoices("requirementId", "requirement_id"),
    )
    source_type: str = Field(
        default="",
        validation_alias=AliasChoices("sourceType", "source_type"),
    )
    source_content: str = Field(
        default="", validation_alias=AliasChoices("sourceContent", "source_content")
    )
    document_download_url: str = Field(
        default="",
        validation_alias=AliasChoices("documentDownloadUrl", "document_download_url"),
    )
    source_archive_download_url: str = Field(
        default="",
        validation_alias=AliasChoices("sourceArchiveDownloadUrl", "source_archive_download_url"),
    )
    document_type: str = Field(
        default="",
        validation_alias=AliasChoices("documentType", "document_type"),
    )
    target_scope: str = Field(
        default="",
        validation_alias=AliasChoices("targetScope", "target_scope"),
    )
    instruction: str = ""
    checkpoint_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("checkpointEnabled", "checkpoint_enabled"),
    )
    current_stage: str = Field(
        default="",
        validation_alias=AliasChoices("currentStage", "current_stage"),
    )
    config_json: str = Field(
        default="",
        validation_alias=AliasChoices("configJson", "config_json"),
    )
    daily_metrics: dict[str, object] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("dailyMetrics", "daily_metrics"),
    )
    # code_risk_analysis 快照字段(可能落在 run 内或顶层,两层都声明以兼容位置漂移)。
    requirement: dict[str, object] | None = None
    bindings: list[dict[str, object]] = Field(default_factory=list)
    existing_tests: dict[str, object] | None = Field(
        default=None,
        validation_alias=AliasChoices("existingTests", "existing_tests"),
    )
    gitlab_credentials_url: str = Field(
        default="",
        validation_alias=AliasChoices("gitlabCredentialsUrl", "gitlab_credentials_url"),
    )


class PlatformSnapshotResponse(BaseModel):
    run: PlatformSnapshotRun
    task_type: str = Field(
        default="",
        validation_alias=AliasChoices("taskType", "task_type", "type"),
    )
    checkpoint_enabled: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("checkpointEnabled", "checkpoint_enabled"),
    )
    current_stage: str = Field(
        default="",
        validation_alias=AliasChoices("currentStage", "current_stage"),
    )
    config_json: str = Field(
        default="",
        validation_alias=AliasChoices("configJson", "config_json"),
    )
    daily_metrics: dict[str, object] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("dailyMetrics", "daily_metrics"),
    )
    # code_risk_analysis 快照字段,同样声明在顶层以兼容位置漂移。
    requirement: dict[str, object] | None = None
    bindings: list[dict[str, object]] = Field(default_factory=list)
    existing_tests: dict[str, object] | None = Field(
        default=None,
        validation_alias=AliasChoices("existingTests", "existing_tests"),
    )
    gitlab_credentials_url: str = Field(
        default="",
        validation_alias=AliasChoices("gitlabCredentialsUrl", "gitlab_credentials_url"),
    )


class PlatformGitlabCredentials(BaseModel):
    connection_id: str = Field(
        default="",
        validation_alias=AliasChoices("connectionId", "connection_id"),
    )
    base_url: str = Field(default="", validation_alias=AliasChoices("baseUrl", "base_url"))
    access_token: str = Field(
        default="",
        validation_alias=AliasChoices("accessToken", "access_token"),
    )
    repository_ids: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("repositoryIds", "repository_ids"),
    )


class PlatformGitlabCredentialsResponse(BaseModel):
    task_id: str = Field(default="", validation_alias=AliasChoices("taskId", "task_id"))
    bindings: list[dict[str, object]] = Field(default_factory=list)
    credentials: list[PlatformGitlabCredentials] = Field(default_factory=list)
