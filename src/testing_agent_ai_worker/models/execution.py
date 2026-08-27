"""Execution lifecycle models for task reporting."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    ERROR = "error"
    CANCELED = "canceled"


class TaskResult(BaseModel):
    task_id: str
    run_id: str = ""
    generate_task_id: str = ""
    status: TaskStatus
    intermediate_json_text: str = ""
    output_yaml: str = ""
    result_summary_json: str = ""
    error_message: str | None = None
    remediation: str | None = None
    started_at: datetime
    finished_at: datetime
    metadata: dict[str, object] = Field(default_factory=dict)


class TaskProgress(BaseModel):
    task_id: str
    run_id: str = ""
    current_stage: str = ""
    stage_status: str = ""
    intermediate_json_text: str = ""
    output_yaml: str = ""
    result_summary_json: str = ""
    error_message: str | None = None
