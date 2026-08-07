"""Shared platform result-summary contract for task executors."""

from __future__ import annotations

import json
from typing import Any

from testing_agent_ai_worker.models.execution import TaskStatus
from testing_agent_ai_worker.models.task import Task


def build_task_result_summary(
    *,
    task: Task,
    status: TaskStatus | str,
    error_message: str | None,
    details: dict[str, Any] | None = None,
) -> str:
    """Serialize common task identity fields plus task-specific summary details."""

    summary: dict[str, Any] = {
        "taskId": task.task_id,
        "runId": task.run_id,
        "generateTaskId": task.generate_task_id,
        "taskType": task.task_type,
        "status": status.value if isinstance(status, TaskStatus) else status,
        "projectId": task.project_id,
        "sprintId": task.sprint_id,
        "requirementId": task.requirement_id,
    }
    if details:
        summary.update(details)
    summary["errorMessage"] = error_message or ""
    return json.dumps(summary, ensure_ascii=False)
