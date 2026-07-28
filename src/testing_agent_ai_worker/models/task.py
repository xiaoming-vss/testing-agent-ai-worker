"""Core task models for the worker polling layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


@dataclass(slots=True)
class LlmCredentials:
    model: str
    api_key: str
    base_url: str


class TaskPayload(BaseModel):
    openapi_content: str
    source_content: str = ""
    document_download_url: str = ""
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
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def has_credentials(self) -> bool:
        return self.payload.llm_credentials is not None

    @property
    def nanobot_session_key(self) -> str:
        return self.run_id.strip()

