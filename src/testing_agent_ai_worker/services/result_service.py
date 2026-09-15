"""Thin result-reporting service.

调用链路：
- `WorkerRunner -> ResultService -> ResultSink`

这里故意保持很薄，主要用于把执行层和平台写回层解耦，方便测试替换 sink。
"""

from __future__ import annotations

from testing_agent_ai_worker.models.execution import TaskProgress, TaskResult
from testing_agent_ai_worker.platform.result_sink import ResultSink


class ResultService:
    """生命周期结果上报门面。"""

    def __init__(self, result_sink: ResultSink) -> None:
        self.result_sink = result_sink

    def mark_started(self, task_id: str, started_at_iso: str) -> None:
        """上报 started。"""

        self.result_sink.mark_started(task_id, started_at_iso)

    def send_heartbeat(self, task_id: str, heartbeat_at_iso: str) -> None:
        """上报 heartbeat。"""

        self.result_sink.send_heartbeat(task_id, heartbeat_at_iso)

    def submit_progress(self, progress: TaskProgress) -> None:
        """上报 progress。"""

        self.result_sink.submit_progress(progress)

    def submit(self, result: TaskResult) -> None:
        """上报 completed。"""

        self.result_sink.submit_result(result)
