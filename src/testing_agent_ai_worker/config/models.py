"""Typed worker configuration models."""

from __future__ import annotations

from pydantic import BaseModel


class WorkerConfig(BaseModel):
    worker_id: str = "testing-agent-ai-worker"
    poll_interval_seconds: int = 10
    heartbeat_interval_seconds: int = 15
    run_once: bool = False


class PlatformConfig(BaseModel):
    base_url: str = ""
    worker_token: str = ""
    task_claim_path: str = "/internal/ai-worker/tasks/claim"
    task_snapshot_path: str = "/internal/ai-worker/tasks/{task_id}/snapshot"
    task_started_path: str = "/internal/ai-worker/tasks/{task_id}/started"
    task_heartbeat_path: str = "/internal/ai-worker/tasks/{task_id}/heartbeat"
    task_progress_path: str = "/internal/ai-worker/tasks/{task_id}/progress"
    task_completed_path: str = "/internal/ai-worker/tasks/{task_id}/completed"
    task_llm_credentials_path: str = "/internal/ai-worker/tasks/{task_id}/llm-credentials"
    project_skills_path: str = "/internal/ai-worker/projects/{project_id}/skills"
    request_timeout_seconds: float = 60.0


class NanobotConfig(BaseModel):
    runtime_root: str = ""
    llm_timeout_seconds: float | None = None
    provider_request_timeout_seconds: float | None = None


class LoggingConfig(BaseModel):
    level: str = "INFO"
    console: bool = True
    dir: str = "logs"
    filename: str = "worker.log"
    retention_days: int = 7


class Settings(BaseModel):
    worker: WorkerConfig = WorkerConfig()
    platform: PlatformConfig = PlatformConfig()
    nanobot: NanobotConfig = NanobotConfig()
    logging: LoggingConfig = LoggingConfig()
