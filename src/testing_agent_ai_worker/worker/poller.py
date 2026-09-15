"""Single-iteration poller wrapper.

调用链路：
- `run_worker_loop/_run_worker_iteration -> TaskPoller.poll`
- `TaskPoller -> TaskService.poll_one`
"""

from __future__ import annotations

from testing_agent_ai_worker.models.task import Task
from testing_agent_ai_worker.services.task_service import TaskService


class TaskPoller:
    """单轮任务获取门面。"""

    def __init__(self, task_service: TaskService) -> None:
        self.task_service = task_service

    def poll(self) -> Task | None:
        """轮询获取一个任务。"""

        return self.task_service.poll_one()
