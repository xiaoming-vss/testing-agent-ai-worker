"""API test case generation executor."""

from __future__ import annotations

import asyncio
from datetime import datetime

from testing_agent_ai_worker.config.models import NanobotConfig
from testing_agent_ai_worker.models.execution import TaskProgress, TaskResult, TaskStatus
from testing_agent_ai_worker.models.task import Task
from testing_agent_ai_worker.nanobot_runtime.config_builder import task_config_path
from testing_agent_ai_worker.nanobot_runtime.paths import (
    resolve_runtime_paths,
    resolve_task_workspace,
)
from testing_agent_ai_worker.tasks.api_case_generate.chain import ChainRunResult, run_chain
from testing_agent_ai_worker.tasks.result_summary import build_task_result_summary
from testing_agent_ai_worker.worker.runner import TaskExecutor


def _resolve_runner_result(result):
    """兼容同步假实现和真实异步 nanobot 调用。"""

    if hasattr(result, "__await__"):
        return asyncio.run(result)
    return result


class ApiCaseNanobotExecutor(TaskExecutor):
    """API 用例生成执行器。"""

    def __init__(
        self,
        *,
        nanobot_config: NanobotConfig,
        chain_runner=run_chain,
    ) -> None:
        self.nanobot_config = nanobot_config
        self.runtime_paths = resolve_runtime_paths(nanobot_config)
        self.chain_runner = chain_runner

    def execute(self, task: Task, started_at: datetime, progress_callback) -> TaskResult:
        """执行 API 用例生成。"""

        if task.task_type != "api_case_generate":
            return TaskResult(
                task_id=task.task_id,
                run_id=task.run_id,
                generate_task_id=task.generate_task_id,
                status=TaskStatus.FAILED,
                error_message=f"不支持的任务类型: {task.task_type}",
                started_at=started_at,
                finished_at=datetime.now().astimezone(),
            )

        workspace = resolve_task_workspace(self.nanobot_config, task)

        with task_config_path(nanobot_config=self.nanobot_config, task=task) as config_path:
            result = self.chain_runner(
                openapi_text=task.payload.openapi_content,
                session_key=task.nanobot_session_key,
                extractor_skill_name="openapi-test-config-extractor",
                generator_skill_name="api-cases-yaml-generator",
                config_path=config_path,
                workspace=str(workspace),
                extra_instruction=self._build_api_instruction(task),
                on_extractor_result=lambda extractor_output: progress_callback(
                    self._build_progress(task, extractor_output)
                ),
            )
            chain_result = _resolve_runner_result(result)
        assert isinstance(chain_result, ChainRunResult)

        return TaskResult(
            task_id=task.task_id,
            run_id=task.run_id,
            generate_task_id=task.generate_task_id,
            status=TaskStatus.SUCCESS,
            intermediate_json_text=chain_result.extractor_output,
            output_yaml=chain_result.generator_output,
            result_summary_json=self._build_result_summary_json(
                task,
                TaskStatus.SUCCESS,
                chain_result.extractor_output,
                chain_result.generator_output,
                None,
            ),
            started_at=started_at,
            finished_at=datetime.now().astimezone(),
        )

    def _build_progress(self, task: Task, extractor_output: str) -> TaskProgress:
        return TaskProgress(
            task_id=task.task_id,
            run_id=task.run_id,
            current_stage="openapi_extract",
            stage_status="running",
            intermediate_json_text=extractor_output,
            result_summary_json=self._build_result_summary_json(
                task,
                "running",
                extractor_output,
                "",
                None,
            ),
        )

    def _build_result_summary_json(
        self,
        task: Task,
        status: TaskStatus | str,
        intermediate_json_text: str,
        output_yaml: str,
        error_message: str | None,
    ) -> str:
        return build_task_result_summary(
            task=task,
            status=status,
            error_message=error_message,
            details={
                "sourceType": task.payload.source_type,
                "jsonLength": len(intermediate_json_text),
                "yamlLength": len(output_yaml),
            },
        )

    @staticmethod
    def _build_api_instruction(task: Task) -> str:
        parts: list[str] = []
        if task.payload.target_scope.strip():
            parts.append(task.payload.target_scope.strip())
        if task.payload.extra_instruction.strip():
            parts.append(task.payload.extra_instruction.strip())
        return "\n".join(parts)
