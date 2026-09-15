import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from testing_agent_ai_worker.models.execution import TaskProgress, TaskResult, TaskStatus
from testing_agent_ai_worker.platform.result_sink import HttpResultSink


class _FakePlatformClient:
    def __init__(self) -> None:
        self.post_calls: list[dict[str, Any]] = []
        self.patch_calls: list[dict[str, Any]] = []

    def post(self, path: str, json_body: dict[str, Any]) -> None:
        self.post_calls.append({"path": path, "json_body": json_body})

    def patch(self, path: str, json_body: dict[str, Any]) -> None:
        self.patch_calls.append({"path": path, "json_body": json_body})


class ResultSinkTests(unittest.TestCase):
    def test_http_result_sink_posts_started_and_heartbeat(self) -> None:
        client = _FakePlatformClient()
        sink = HttpResultSink(
            client=client,  # type: ignore[arg-type]
            worker_id="worker-1",
            started_path_template="/tasks/{task_id}/started",
            heartbeat_path_template="/tasks/{task_id}/heartbeat",
            progress_path_template="/tasks/{task_id}/progress",
            completed_path_template="/tasks/{task_id}/completed",
        )

        sink.mark_started("task-1", "2026-06-23T10:00:00+08:00")
        sink.send_heartbeat("task-1", "2026-06-23T10:00:05+08:00")

        self.assertEqual(
            client.post_calls,
            [
                {
                    "path": "/tasks/task-1/started",
                    "json_body": {
                        "workerId": "worker-1",
                        "startedAt": "2026-06-23T10:00:00+08:00",
                    },
                },
                {
                    "path": "/tasks/task-1/heartbeat",
                    "json_body": {
                        "workerId": "worker-1",
                        "heartbeatAt": "2026-06-23T10:00:05+08:00",
                    },
                },
            ],
        )

    def test_http_result_sink_patches_progress_without_completion_fields(self) -> None:
        client = _FakePlatformClient()
        sink = HttpResultSink(
            client=client,  # type: ignore[arg-type]
            worker_id="worker-1",
            started_path_template="/tasks/{task_id}/started",
            heartbeat_path_template="/tasks/{task_id}/heartbeat",
            progress_path_template="/tasks/{task_id}/progress",
            completed_path_template="/tasks/{task_id}/completed",
        )
        summary = json.dumps({"status": "running", "caseCount": 1}, ensure_ascii=False)

        sink.submit_progress(
            TaskProgress(
                task_id="task-1",
                run_id="run-1",
                current_stage="openapi_extract",
                stage_status="running",
                intermediate_json_text='{"cases":[]}',
                output_yaml="",
                result_summary_json=summary,
            )
        )

        self.assertEqual(1, len(client.patch_calls))
        progress_call = client.patch_calls[0]
        self.assertEqual("/tasks/task-1/progress", progress_call["path"])
        self.assertEqual(
            {
                "workerId": "worker-1",
                "taskId": "task-1",
                "runId": "run-1",
                "currentStage": "openapi_extract",
                "stageStatus": "running",
                "errorMessage": "",
                "configJson": '{"cases":[]}',
                "resultYaml": "",
                "resultSummaryJson": summary,
            },
            progress_call["json_body"],
        )
        self.assertNotIn("status", progress_call["json_body"])
        self.assertNotIn("startedAt", progress_call["json_body"])
        self.assertNotIn("finishedAt", progress_call["json_body"])

    def test_http_result_sink_posts_completed_payload(self) -> None:
        client = _FakePlatformClient()
        sink = HttpResultSink(
            client=client,  # type: ignore[arg-type]
            worker_id="worker-1",
            started_path_template="/tasks/{task_id}/started",
            heartbeat_path_template="/tasks/{task_id}/heartbeat",
            progress_path_template="/tasks/{task_id}/progress",
            completed_path_template="/tasks/{task_id}/completed",
        )
        started_at = datetime.fromisoformat("2026-06-23T10:00:00+08:00")
        finished_at = datetime.fromisoformat("2026-06-23T10:00:08+08:00")

        sink.submit_result(
            TaskResult(
                task_id="task-1",
                run_id="run-1",
                generate_task_id="generate-1",
                status=TaskStatus.SUCCESS,
                intermediate_json_text='{"cases":[]}',
                output_yaml="cases: []",
                result_summary_json='{"status":"success"}',
                started_at=started_at,
                finished_at=finished_at,
            )
        )

        self.assertEqual(
            client.post_calls[0],
            {
                "path": "/tasks/task-1/completed",
                "json_body": {
                    "workerId": "worker-1",
                    "taskId": "task-1",
                    "runId": "run-1",
                    "status": "success",
                    "startedAt": "2026-06-23T10:00:00+08:00",
                    "finishedAt": "2026-06-23T10:00:08+08:00",
                    "errorMessage": "",
                    "remediation": "",
                    "configJson": '{"cases":[]}',
                    "resultYaml": "cases: []",
                    "resultSummaryJson": '{"status":"success"}',
                },
            },
        )

    def test_http_result_sink_posts_remediation_on_failure(self) -> None:
        client = _FakePlatformClient()
        sink = HttpResultSink(
            client=client,  # type: ignore[arg-type]
            worker_id="worker-1",
            started_path_template="/tasks/{task_id}/started",
            heartbeat_path_template="/tasks/{task_id}/heartbeat",
            progress_path_template="/tasks/{task_id}/progress",
            completed_path_template="/tasks/{task_id}/completed",
        )
        started_at = datetime.fromisoformat("2026-06-23T10:00:00+08:00")
        finished_at = datetime.fromisoformat("2026-06-23T10:00:08+08:00")

        sink.submit_result(
            TaskResult(
                task_id="task-1",
                run_id="run-1",
                status=TaskStatus.FAILED,
                error_message="仓库 repo-1 基线解析失败",
                remediation="请手工指定基线 / 检查 PAT",
                started_at=started_at,
                finished_at=finished_at,
            )
        )

        self.assertEqual(
            "请手工指定基线 / 检查 PAT", client.post_calls[0]["json_body"]["remediation"]
        )


if __name__ == "__main__":
    unittest.main()
