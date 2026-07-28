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
        default="",
        validation_alias=AliasChoices("sourceContent", "source_content")
    )
    document_download_url: str = Field(
        default="",
        validation_alias=AliasChoices("documentDownloadUrl", "document_download_url"),
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

class PlatformProjectSkill(BaseModel):
    skill_space_id: str = Field(
        default="",
        validation_alias=AliasChoices("skillSpaceId", "skill_space_id"),
    )
    project_id: str = Field(default="", validation_alias=AliasChoices("projectId", "project_id"))
    filename: str = ""
    download_url: str = Field(
        default="",
        validation_alias=AliasChoices("downloadUrl", "download_url"),
    )
    hash: str = ""
    size: int = 0
    version: int = 0


class PlatformProjectSkillListResponse(BaseModel):
    skills: list[PlatformProjectSkill] = Field(default_factory=list)


