"""Backward-compatible task executor imports.

New code should import executors from `testing_agent_ai_worker.tasks.<task_type>`.
"""

from __future__ import annotations

from datetime import datetime

from testing_agent_ai_worker.models.execution import TaskResult, TaskStatus
from testing_agent_ai_worker.models.task import Task
from testing_agent_ai_worker.tasks.api_case_generate.chain import ChainRunResult
from testing_agent_ai_worker.tasks.api_case_generate.executor import ApiCaseNanobotExecutor
from testing_agent_ai_worker.tasks.functional_case_generate.chain import (
    FunctionalChainRunResult,
    run_functional_chain,
    run_skill_step,
)
from testing_agent_ai_worker.tasks.functional_case_generate.detailed_batches import (
    run_functional_detailed_case_batches,
)
from testing_agent_ai_worker.tasks.functional_case_generate.executor import (
    EMPTY_CASES_JSON,
    FunctionalCaseNanobotExecutor,
)
from testing_agent_ai_worker.tasks.requirement_analysis.chain import (
    RequirementAnalysisChainRunResult,
)
from testing_agent_ai_worker.tasks.requirement_analysis.executor import (
    REQUIREMENT_ANALYSIS_FIRST_SKILL_NAME,
    REQUIREMENT_ANALYSIS_SECOND_SKILL_NAME,
    REQUIREMENT_ANALYSIS_THIRD_SKILL_NAME,
    RequirementAnalysisNanobotExecutor,
)
from testing_agent_ai_worker.worker.dispatcher import WorkerTaskDispatcherExecutor
from testing_agent_ai_worker.worker.runner import TaskExecutor

__all__ = [
    "ApiCaseNanobotExecutor",
    "ChainRunResult",
    "EMPTY_CASES_JSON",
    "FunctionalCaseNanobotExecutor",
    "FunctionalChainRunResult",
    "PlaceholderTaskExecutor",
    "REQUIREMENT_ANALYSIS_FIRST_SKILL_NAME",
    "REQUIREMENT_ANALYSIS_SECOND_SKILL_NAME",
    "REQUIREMENT_ANALYSIS_THIRD_SKILL_NAME",
    "RequirementAnalysisChainRunResult",
    "RequirementAnalysisNanobotExecutor",
    "WorkerTaskDispatcherExecutor",
    "run_functional_chain",
    "run_functional_detailed_case_batches",
    "run_skill_step",
]


class PlaceholderTaskExecutor(TaskExecutor):
    """历史占位执行器，当前仅保留为回退实现。"""

    def execute(self, task: Task, started_at: datetime, progress_callback) -> TaskResult:
        return TaskResult(
            task_id=task.task_id,
            run_id=task.run_id,
            generate_task_id=task.generate_task_id,
            status=TaskStatus.FAILED,
            error_message=f"任务类型 {task.task_type} 的执行器尚未接入",
            started_at=started_at,
            finished_at=datetime.now().astimezone(),
        )
