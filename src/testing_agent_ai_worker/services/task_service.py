"""Thin application service for polling one task from the platform."""

from __future__ import annotations

from testing_agent_ai_worker.models.task import Task
from testing_agent_ai_worker.platform.task_source import TaskSource


class TaskService:
    """Read one executable task from the configured task source."""

    def __init__(self, task_source: TaskSource) -> None:
        self.task_source = task_source

    def poll_one(self) -> Task | None:
        """读取一个可执行任务。"""

        return self.task_source.poll_task()
