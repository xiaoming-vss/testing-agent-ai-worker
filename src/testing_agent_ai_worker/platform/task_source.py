"""Platform task source and protocol adaptation.

调用链路：
- `TaskPoller.poll -> TaskService.poll_one -> HttpClaimTaskSource.poll_task`
- `poll_task -> claim -> snapshot -> llm-credentials`
- `poll_task -> _to_domain_task`

这里的职责是把平台协议对象收敛成 worker 内部 `Task`，不承担实际执行逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from testing_agent_ai_worker.platform.errors import TaskSourceError
from testing_agent_ai_worker.models.task import LlmCredentials, Task, TaskPayload
from testing_agent_ai_worker.platform.http_client import PlatformHttpClient
from testing_agent_ai_worker.platform.schemas import (
    PlatformClaimTask,
    PlatformLlmCredentials,
    PlatformSnapshotResponse,
)


class TaskSource(Protocol):
    def poll_task(self) -> Task | None: ...


@dataclass(slots=True)
class HttpClaimTaskSource:
    client: PlatformHttpClient
    claim_path: str
    snapshot_path_template: str
    llm_credentials_path_template: str
    worker_id: str

    def poll_task(self) -> Task | None:
        """执行一次完整的平台任务获取流程。"""

        try:
            claim_payload = self.client.post(
                self.claim_path,
                json_body={"workerId": self.worker_id},
            )
            if not claim_payload:
                return None

            claimed_task = PlatformClaimTask.model_validate(claim_payload)
            snapshot_payload = self.client.get(
                self.snapshot_path_template.format(task_id=claimed_task.task_id)
            )
            if not snapshot_payload:
                raise TaskSourceError(f"任务快照为空: task_id={claimed_task.task_id}")

            snapshot_response = PlatformSnapshotResponse.model_validate(snapshot_payload)
            task = self._to_domain_task(
                claimed_task,
                snapshot_response,
                raw_claim=claim_payload,
                raw_snapshot=snapshot_payload,
            )

            if claimed_task.llm_connection_id and self.llm_credentials_path_template:
                try:
                    credentials = self._fetch_llm_credentials(task.task_id)
                    task.payload.llm_credentials = credentials
                except Exception as exc:
                    task.credential_error = str(exc)

            return task
        except httpx.TimeoutException as exc:  # pragma: no cover
            raise TaskSourceError(
                f"领取任务超时: path={self.claim_path} timeout={self.client.timeout_seconds}s"
            ) from exc
        except Exception as exc:
            if isinstance(exc, TaskSourceError):
                raise
            raise TaskSourceError(f"领取任务失败: {exc}") from exc

    def _fetch_llm_credentials(self, task_id: str) -> LlmCredentials:
        """补拉模型凭证。

        这里和 claim/snapshot 分开调用，是为了继续兼容现有平台的三段式协议。
        """

        path = self.llm_credentials_path_template.format(task_id=task_id)
        payload = self.client.get_with_retry(path)
        if not payload:
            raise TaskSourceError(f"LLM 凭证响应为空: task_id={task_id}")
        credentials = PlatformLlmCredentials.model_validate(payload)
        return LlmCredentials(
            model=credentials.model_id,
            api_key=credentials.api_key,
            base_url=credentials.base_url,
        )

    def _to_domain_task(
        self,
        claimed_task: PlatformClaimTask,
        snapshot_response: PlatformSnapshotResponse,
        *,
        raw_claim: dict[str, object],
        raw_snapshot: dict[str, object],
    ) -> Task:
        """把平台 claim/snapshot 响应映射成内部任务模型。

        字段优先级需要兼容平台响应位置漂移，因此会做多层回退合并。
        """

        snapshot_task = snapshot_response.run

        snapshot_checkpoint_enabled = snapshot_task.checkpoint_enabled
        snapshot_current_stage = snapshot_task.current_stage
        snapshot_config_json = snapshot_task.config_json

        if snapshot_response.checkpoint_enabled is not None:
            snapshot_checkpoint_enabled = snapshot_response.checkpoint_enabled
        # 兼容 checkpoint 字段可能落在 snapshot 顶层，也可能仍落在 snapshot.run 内。
        snapshot_current_stage = snapshot_response.current_stage or snapshot_current_stage
        snapshot_config_json = snapshot_response.config_json or snapshot_config_json

        checkpoint_enabled = (
            snapshot_checkpoint_enabled
            if snapshot_checkpoint_enabled
            else bool(claimed_task.checkpoint_enabled)
        )
        current_stage = snapshot_current_stage or claimed_task.current_stage
        config_json = snapshot_config_json or claimed_task.config_json
        # 任务类型也保持和老平台一致的回退顺序，避免后端字段来源切换时取错值。
        task_type = snapshot_response.task_type or snapshot_task.task_type or claimed_task.task_type
        document_type = self._resolve_document_type(snapshot_task)
        source_type = self._resolve_source_type(task_type, snapshot_task, document_type)
        daily_metrics = snapshot_response.daily_metrics or snapshot_task.daily_metrics

        return Task(
            claim_id=claimed_task.claim_id or claimed_task.task_id,
            task_id=claimed_task.task_id,
            run_id=claimed_task.run_id or snapshot_task.run_id,
            generate_task_id=claimed_task.generate_task_id or snapshot_task.generate_task_id,
            task_type=task_type,
            name=snapshot_task.name,
            project_id=claimed_task.project_id or snapshot_task.project_id,
            sprint_id=claimed_task.sprint_id or snapshot_task.sprint_id,
            requirement_id=claimed_task.requirement_id or snapshot_task.requirement_id,
            lease_seconds=claimed_task.lease_seconds,
            checkpoint_enabled=checkpoint_enabled,
            current_stage=current_stage,
            config_json=config_json,
            payload=TaskPayload(
                openapi_content=snapshot_task.source_content,
                source_content=snapshot_task.source_content,
                document_download_url=snapshot_task.document_download_url,
                document_type=document_type,
                source_type=source_type,
                target_scope=snapshot_task.target_scope,
                extra_instruction=snapshot_task.instruction,
                daily_metrics=daily_metrics,
                metadata={
                    "name": snapshot_task.name,
                    "runId": claimed_task.run_id or snapshot_task.run_id,
                    "generateTaskId": claimed_task.generate_task_id or snapshot_task.generate_task_id,
                    "projectId": claimed_task.project_id or snapshot_task.project_id,
                    "sprintId": claimed_task.sprint_id or snapshot_task.sprint_id,
                    "requirementId": claimed_task.requirement_id or snapshot_task.requirement_id,
                    "targetScope": snapshot_task.target_scope,
                    "documentDownloadUrl": snapshot_task.document_download_url,
                    "documentType": document_type,
                    "dailyMetrics": daily_metrics,
                    "checkpointEnabled": checkpoint_enabled,
                    "currentStage": current_stage,
                },
            ),
            raw={
                "claim": raw_claim,
                "snapshot": raw_snapshot,
            },
        )

    @staticmethod
    def _resolve_document_type(snapshot_task: object) -> str:
        document_type = getattr(snapshot_task, "document_type", "").strip().lower()
        if document_type:
            return HttpClaimTaskSource._normalize_document_type(document_type)

        source_type = getattr(snapshot_task, "source_type", "").strip().lower()
        return HttpClaimTaskSource._normalize_document_type(source_type)

    @staticmethod
    def _resolve_source_type(task_type: str, snapshot_task: object, document_type: str) -> str:
        normalized_task_type = task_type.strip().lower()
        source_type = getattr(snapshot_task, "source_type", "").strip().lower()
        if normalized_task_type == "api_case_generate":
            return source_type or "openapi"
        if normalized_task_type in {"functional_case_generate", "requirement_analysis"}:
            return document_type
        return source_type

    @staticmethod
    def _normalize_document_type(source_type: str) -> str:
        if source_type in {"word", "docx"}:
            return "word"
        if source_type in {"text", "txt"}:
            return "text"
        return source_type




