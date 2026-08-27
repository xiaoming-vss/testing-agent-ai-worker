"""Platform lifecycle callback sink.

调用链路：
- `WorkerRunner -> ResultService -> HttpResultSink`
- `HttpResultSink -> started/heartbeat/progress/completed`

这里统一维护 worker 内部结果模型到平台接口字段的映射关系。
"""

from __future__ import annotations

from typing import Protocol

from testing_agent_ai_worker.models.execution import TaskProgress, TaskResult
from testing_agent_ai_worker.platform.http_client import PlatformHttpClient


class ResultSink(Protocol):
    def mark_started(self, task_id: str, started_at_iso: str) -> None: ...
    def send_heartbeat(self, task_id: str, heartbeat_at_iso: str) -> None: ...
    def submit_progress(self, progress: TaskProgress) -> None: ...
    def submit_result(self, result: TaskResult) -> None: ...


class HttpResultSink:
    """把内部生命周期事件写回平台接口。"""

    def __init__(
        self,
        *,
        client: PlatformHttpClient,
        worker_id: str,
        started_path_template: str,
        heartbeat_path_template: str,
        progress_path_template: str,
        completed_path_template: str,
    ) -> None:
        self.client = client
        self.worker_id = worker_id
        self.started_path_template = started_path_template
        self.heartbeat_path_template = heartbeat_path_template
        self.progress_path_template = progress_path_template
        self.completed_path_template = completed_path_template

    def mark_started(self, task_id: str, started_at_iso: str) -> None:
        """回传 started。"""

        self.client.post(
            self.started_path_template.format(task_id=task_id),
            json_body={
                "workerId": self.worker_id,
                "startedAt": started_at_iso,
            },
        )

    def send_heartbeat(self, task_id: str, heartbeat_at_iso: str) -> None:
        """回传 heartbeat。"""

        self.client.post(
            self.heartbeat_path_template.format(task_id=task_id),
            json_body={
                "workerId": self.worker_id,
                "heartbeatAt": heartbeat_at_iso,
            },
        )

    def submit_progress(self, progress: TaskProgress) -> None:
        """回传 progress。

        平台沿用 `configJson/resultYaml/resultSummaryJson` 三个通用字段承载中间结果。
        """

        self.client.patch(
            self.progress_path_template.format(task_id=progress.task_id),
            json_body={
                "workerId": self.worker_id,
                "taskId": progress.task_id,
                "runId": progress.run_id,
                "currentStage": progress.current_stage,
                "stageStatus": progress.stage_status,
                "errorMessage": progress.error_message or "",
                "configJson": progress.intermediate_json_text,
                "resultYaml": progress.output_yaml,
                "resultSummaryJson": progress.result_summary_json,
            },
        )

    def submit_result(self, result: TaskResult) -> None:
        """回传 completed。"""

        self.client.post(
            self.completed_path_template.format(task_id=result.task_id),
            json_body={
                "workerId": self.worker_id,
                "taskId": result.task_id,
                "runId": result.run_id,
                "status": result.status.value,
                "startedAt": result.started_at.isoformat(),
                "finishedAt": result.finished_at.isoformat(),
                "errorMessage": result.error_message or "",
                "remediation": result.remediation or "",
                "configJson": result.intermediate_json_text,
                "resultYaml": result.output_yaml,
                "resultSummaryJson": result.result_summary_json,
            },
        )
