"""Requirement analysis executor."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from testing_agent_ai_worker.config.models import NanobotConfig
from testing_agent_ai_worker.models.execution import TaskProgress, TaskResult, TaskStatus
from testing_agent_ai_worker.models.task import Task
from testing_agent_ai_worker.nanobot_runtime.config_builder import task_config_path
from testing_agent_ai_worker.nanobot_runtime.paths import (
    resolve_runtime_paths,
    resolve_task_workspace,
)
from testing_agent_ai_worker.tasks.requirement_analysis.chain import (
    RequirementAnalysisChainRunResult,
    run_requirement_analysis_chain,
    run_skill_step,
)
from testing_agent_ai_worker.tasks.requirement_analysis.checkpoint import (
    REQUIREMENT_ANALYSIS_CHECKPOINT_STAGES,
    REQUIREMENT_ANALYSIS_INITIAL_STAGE,
    execute_checkpoint_task,
)
from testing_agent_ai_worker.tasks.requirement_analysis.source_downloader import (
    RequirementSourceDownloader,
)
from testing_agent_ai_worker.tasks.result_summary import build_task_result_summary
from testing_agent_ai_worker.worker.runner import TaskExecutor

REQUIREMENT_ANALYSIS_FIRST_SKILL_NAME = "extract-docx-enhanced-text"
REQUIREMENT_ANALYSIS_SECOND_SKILL_NAME = "prd-requirement-writing-skill"
REQUIREMENT_ANALYSIS_THIRD_SKILL_NAME = "prd-feature-understanding-skill"
SUPPORTED_REQUIREMENT_ANALYSIS_DOCUMENT_TYPES = {"text", "word"}
LOGGER = logging.getLogger("testing_agent_ai_worker")


def normalize_requirement_analysis_document_type(document_type: str) -> str:
    normalized = document_type.strip().lower()
    if normalized in {"word", "docx"}:
        return "word"
    if normalized in {"text", "txt"}:
        return "text"
    return normalized


def _resolve_runner_result(result):
    """兼容同步假实现和真实异步 nanobot 调用。"""

    if hasattr(result, "__await__"):
        return asyncio.run(result)
    return result


class RequirementAnalysisNanobotExecutor(TaskExecutor):
    """需求分析执行器。"""

    def __init__(
        self,
        *,
        nanobot_config: NanobotConfig,
        chain_runner=run_requirement_analysis_chain,
        skill_runner=run_skill_step,
        first_skill_name: str = REQUIREMENT_ANALYSIS_FIRST_SKILL_NAME,
        second_skill_name: str = REQUIREMENT_ANALYSIS_SECOND_SKILL_NAME,
        third_skill_name: str = REQUIREMENT_ANALYSIS_THIRD_SKILL_NAME,
        source_downloader: RequirementSourceDownloader | None = None,
    ) -> None:
        self.nanobot_config = nanobot_config
        self.runtime_paths = resolve_runtime_paths(nanobot_config)
        self.chain_runner = chain_runner
        self.skill_runner = skill_runner
        self.first_skill_name = first_skill_name
        self.second_skill_name = second_skill_name
        self.third_skill_name = third_skill_name
        self.source_downloader = source_downloader

    def execute(self, task: Task, started_at: datetime, progress_callback) -> TaskResult | None:
        """执行需求分析任务。"""

        if task.task_type != "requirement_analysis":
            return TaskResult(
                task_id=task.task_id,
                run_id=task.run_id,
                generate_task_id=task.generate_task_id,
                status=TaskStatus.FAILED,
                error_message=f"不支持的任务类型: {task.task_type}",
                started_at=started_at,
                finished_at=datetime.now().astimezone(),
            )
        task.payload.document_type = normalize_requirement_analysis_document_type(
            task.payload.document_type
        )
        if task.payload.document_type not in SUPPORTED_REQUIREMENT_ANALYSIS_DOCUMENT_TYPES:
            return TaskResult(
                task_id=task.task_id,
                run_id=task.run_id,
                generate_task_id=task.generate_task_id,
                status=TaskStatus.FAILED,
                error_message=f"不支持的 document_type: {task.payload.document_type}",
                started_at=started_at,
                finished_at=datetime.now().astimezone(),
            )

        workspace = resolve_task_workspace(self.nanobot_config, task)

        with task_config_path(nanobot_config=self.nanobot_config, task=task) as config_path:
            checkpoint_stage = task.current_stage.strip()
            checkpoint_mode = (
                task.checkpoint_enabled
                or checkpoint_stage in REQUIREMENT_ANALYSIS_CHECKPOINT_STAGES
            )
            if task.checkpoint_enabled and not checkpoint_stage:
                checkpoint_stage = REQUIREMENT_ANALYSIS_INITIAL_STAGE
                task.current_stage = checkpoint_stage
            LOGGER.info(
                "requirement analysis execution mode: task_id=%s checkpoint=%s current_stage=%s "
                "document_type=%s config_chars=%s",
                task.task_id,
                checkpoint_mode,
                task.current_stage,
                task.payload.document_type,
                len(task.config_json or ""),
            )
            if checkpoint_mode:
                return execute_checkpoint_task(
                    task=task,
                    started_at=started_at,
                    progress_callback=progress_callback,
                    config_path=config_path,
                    workspace=workspace,
                    skill_runner=self.skill_runner,
                    source_downloader=self.source_downloader,
                    first_skill_name=self.first_skill_name,
                    second_skill_name=self.second_skill_name,
                    third_skill_name=self.third_skill_name,
                )

            source_path = self._download_source(task, workspace)
            chain_stage_state = {"first_step_output": ""}

            def report_first_step(first_step_output: str) -> None:
                chain_stage_state["first_step_output"] = first_step_output
                progress_callback(
                    self._build_progress(
                        task,
                        current_stage="extracting_text",
                        first_step_output=first_step_output,
                    )
                )

            def report_second_step(second_step_output: str) -> None:
                progress_callback(
                    self._build_progress(
                        task,
                        current_stage="writing_requirement",
                        first_step_output=chain_stage_state["first_step_output"],
                        second_step_output=second_step_output,
                    )
                )

            result = self.chain_runner(
                source_text=str(source_path),
                session_key=task.nanobot_session_key,
                first_skill_name=self.first_skill_name,
                second_skill_name=self.second_skill_name,
                third_skill_name=self.third_skill_name,
                config_path=config_path,
                workspace=str(workspace),
                extra_instruction=task.payload.extra_instruction,
                on_first_step_result=report_first_step,
                on_second_step_result=report_second_step,
            )
            chain_result = _resolve_runner_result(result)
        assert isinstance(chain_result, RequirementAnalysisChainRunResult)

        config_json = self._build_config_json(
            task=task,
            first_step_output=chain_result.first_step_output,
            second_step_output=chain_result.second_step_output,
        )
        return TaskResult(
            task_id=task.task_id,
            run_id=task.run_id,
            generate_task_id=task.generate_task_id,
            status=TaskStatus.SUCCESS,
            intermediate_json_text=config_json,
            output_yaml=chain_result.final_output,
            result_summary_json=self._build_result_summary_json(
                task=task,
                status=TaskStatus.SUCCESS,
                config_json=config_json,
                output_yaml=chain_result.final_output,
                error_message=None,
            ),
            started_at=started_at,
            finished_at=datetime.now().astimezone(),
        )

    def _build_progress(
        self,
        task: Task,
        *,
        current_stage: str,
        first_step_output: str,
        second_step_output: str | None = None,
    ) -> TaskProgress:
        config_json = self._build_config_json(
            task=task,
            first_step_output=first_step_output,
            second_step_output=second_step_output,
        )
        return TaskProgress(
            task_id=task.task_id,
            run_id=task.run_id,
            current_stage=current_stage,
            stage_status="running",
            intermediate_json_text=config_json,
            output_yaml="",
            result_summary_json=self._build_result_summary_json(
                task=task,
                status="running",
                config_json=config_json,
                output_yaml="",
                error_message=None,
            ),
        )

    def _build_config_json(
        self,
        *,
        task: Task,
        first_step_output: str,
        second_step_output: str | None = None,
    ) -> str:
        config = {
            "firstStepOutput": first_step_output,
        }
        if second_step_output is not None:
            config["secondStepOutput"] = second_step_output
        return json.dumps(config, ensure_ascii=False, indent=2)

    def _build_result_summary_json(
        self,
        *,
        task: Task,
        status: TaskStatus | str,
        config_json: str,
        output_yaml: str,
        error_message: str | None,
    ) -> str:
        return build_task_result_summary(
            task=task,
            status=status,
            error_message=error_message,
            details={
                "sourceType": task.payload.source_type,
                "documentType": task.payload.document_type,
                "configJsonLength": len(config_json),
                "resultLength": len(output_yaml),
            },
        )

    def _download_source(self, task: Task, workspace) -> Path:
        if self.source_downloader is None:
            raise ValueError("requirement_analysis source_downloader is required")
        return self.source_downloader.download_source(
            document_download_url=task.payload.document_download_url,
            document_type=task.payload.document_type,
            task=task,
            workspace=workspace,
        )
