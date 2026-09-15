"""Functional test case generation executor."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from uuid import uuid4

from testing_agent_ai_worker.config.models import NanobotConfig
from testing_agent_ai_worker.models.execution import TaskProgress, TaskResult, TaskStatus
from testing_agent_ai_worker.models.task import Task
from testing_agent_ai_worker.nanobot_runtime.config_builder import task_config_path
from testing_agent_ai_worker.nanobot_runtime.paths import (
    resolve_runtime_paths,
    resolve_task_workspace,
)
from testing_agent_ai_worker.tasks.functional_case_generate.chain import (
    FunctionalChainRunResult,
    run_functional_chain,
    run_skill_step,
)
from testing_agent_ai_worker.tasks.functional_case_generate.checkpoint import (
    EMPTY_CASES_JSON,
    execute_checkpoint_task,
)
from testing_agent_ai_worker.tasks.functional_case_generate.detailed_batches import (
    run_functional_detailed_case_batches,
)
from testing_agent_ai_worker.tasks.functional_case_generate.summary import (
    build_config_json,
    build_progress,
    build_result_summary_json,
)
from testing_agent_ai_worker.worker.runner import TaskExecutor

from .validation import ValidationContext, context

SUPPORTED_FUNCTIONAL_SOURCE_TYPES = {"text", "word"}
LOGGER = logging.getLogger("testing_agent_ai_worker")


def _resolve_functional_document_type(task: Task) -> str:
    document_type = (task.payload.document_type or "").strip().lower()
    if not document_type:
        document_type = (task.payload.source_type or "").strip().lower()
    if document_type in {"docx", "word"}:
        return "word"
    if document_type in {"txt", "text"}:
        return "text"
    return document_type


def _resolve_runner_result(result):
    """兼容同步假实现和真实异步 nanobot 调用。"""

    if hasattr(result, "__await__"):
        return asyncio.run(result)
    return result


class FunctionalCaseNanobotExecutor(TaskExecutor):
    """功能测试用例生成执行器。

    支持两种模式：
    - 非 checkpoint：一次性顺序跑完三段链路
    - checkpoint：按 currentStage 恢复执行并在中间阶段停住
    """

    def __init__(
        self,
        *,
        nanobot_config: NanobotConfig,
        chain_runner=run_functional_chain,
        skill_runner=run_skill_step,
        detailed_batch_runner=run_functional_detailed_case_batches,
    ) -> None:
        self.nanobot_config = nanobot_config
        self.runtime_paths = resolve_runtime_paths(nanobot_config)
        self.chain_runner = chain_runner
        self.skill_runner = skill_runner
        self.detailed_batch_runner = detailed_batch_runner

    def execute(self, task: Task, started_at: datetime, progress_callback) -> TaskResult | None:
        workspace = resolve_task_workspace(self.nanobot_config, task)

        def report(event):
            progress_callback(
                TaskProgress(
                    task_id=task.task_id,
                    run_id=task.run_id,
                    current_stage=event["stage"],
                    stage_status="running",
                    result_summary_json=json.dumps({"outputValidation": event}, ensure_ascii=False),
                )
            )

        token = context.set(
            ValidationContext(
                diagnostic_dir=workspace
                / "diagnostics"
                / "functional-output"
                / str(task.run_id)
                / uuid4().hex,
                report=report,
            )
        )
        try:
            return self._execute(task, started_at, progress_callback)
        finally:
            context.reset(token)

    def _execute(self, task: Task, started_at: datetime, progress_callback) -> TaskResult | None:
        """执行功能测试任务主入口。"""

        if task.task_type != "functional_case_generate":
            return TaskResult(
                task_id=task.task_id,
                run_id=task.run_id,
                generate_task_id=task.generate_task_id,
                status=TaskStatus.FAILED,
                error_message=f"不支持的任务类型: {task.task_type}",
                started_at=started_at,
                finished_at=datetime.now().astimezone(),
            )
        document_type = _resolve_functional_document_type(task)
        if document_type not in SUPPORTED_FUNCTIONAL_SOURCE_TYPES:
            return TaskResult(
                task_id=task.task_id,
                run_id=task.run_id,
                generate_task_id=task.generate_task_id,
                status=TaskStatus.FAILED,
                error_message=f"不支持的 document_type: {document_type}",
                started_at=started_at,
                finished_at=datetime.now().astimezone(),
            )

        workspace = resolve_task_workspace(self.nanobot_config, task)

        with task_config_path(nanobot_config=self.nanobot_config, task=task) as config_path:
            self._log_execution_context(task, config_path=config_path, workspace=workspace)
            # checkpoint 模式优先从平台下发的 currentStage/configJson 恢复。
            if task.checkpoint_enabled or (
                task.current_stage == "detailed_cases"
                and json.loads(task.config_json or "{}").get("revisionInstruction")
            ):
                return execute_checkpoint_task(
                    task=task,
                    started_at=started_at,
                    progress_callback=progress_callback,
                    config_path=config_path,
                    workspace=workspace,
                    skill_runner=self.skill_runner,
                    detailed_batch_runner=self.detailed_batch_runner,
                )

            # 非 checkpoint 模式下，使用临时状态保存前两段产物，供 progress 和最后一段分片生成复用。
            source_text = task.payload.source_content
            stage_state = {
                "requirement_analysis_json": "",
                "case_names_json": "",
            }

            resume = {}
            if task.current_stage in {"case_names", "detailed_cases"}:
                config = json.loads(task.config_json or "{}")

                def text_field(key):
                    value = config.get(key)
                    return (
                        value
                        if isinstance(value, str)
                        else json.dumps(value, ensure_ascii=False)
                        if value is not None
                        else ""
                    )

                resume = {
                    "resume_stage": task.current_stage,
                    "prior_analysis": text_field("requirementAnalysis"),
                    "prior_case_names": text_field("caseNames"),
                }
                stage_state["requirement_analysis_json"] = resume["prior_analysis"]
                stage_state["case_names_json"] = resume["prior_case_names"]
            result = self.chain_runner(
                **resume,
                source_text=source_text,
                session_key=task.nanobot_session_key,
                analysis_skill_name="analyze-functional-requirements",
                case_name_skill_name="generate-solution-test-points",
                detailed_case_skill_name="generate-solution-test-cases",
                config_path=config_path,
                workspace=str(workspace),
                extra_instruction=task.payload.extra_instruction,
                on_requirement_analysis_result=lambda requirement_analysis_output: (
                    self._report_requirement_analysis(
                        task,
                        progress_callback,
                        stage_state,
                        requirement_analysis_output,
                    )
                ),
                on_case_names_result=lambda case_names_output: self._report_case_names(
                    task,
                    progress_callback,
                    stage_state,
                    case_names_output,
                ),
                on_detailed_cases_progress=lambda accumulated_result, _model_name, _index, _total: (
                    progress_callback(
                        build_progress(
                            task,
                            current_stage="detailed_cases",
                            stage_status="running",
                            requirement_analysis_json=stage_state["requirement_analysis_json"],
                            case_names_json=stage_state["case_names_json"],
                            detailed_cases_json=accumulated_result,
                        )
                    )
                ),
            )
            chain_result = _resolve_runner_result(result)
            assert isinstance(chain_result, FunctionalChainRunResult)

            config_json = build_config_json(
                requirement_analysis_json=chain_result.requirement_analysis_output,
                case_names_json=chain_result.case_names_output,
            )
            return TaskResult(
                task_id=task.task_id,
                run_id=task.run_id,
                generate_task_id=task.generate_task_id,
                status=TaskStatus.SUCCESS,
                intermediate_json_text=config_json,
                output_yaml=chain_result.detailed_cases_output,
                result_summary_json=build_result_summary_json(
                    task=task,
                    status=TaskStatus.SUCCESS,
                    config_json=config_json,
                    detailed_cases_json=chain_result.detailed_cases_output,
                    error_message=None,
                ),
                started_at=started_at,
                finished_at=datetime.now().astimezone(),
            )

    def _report_requirement_analysis(
        self,
        task: Task,
        progress_callback,
        stage_state: dict[str, str],
        requirement_analysis_output: str,
    ) -> None:
        """记录 requirement_analysis 产物并上报 progress。"""

        stage_state["requirement_analysis_json"] = requirement_analysis_output
        progress_callback(
            build_progress(
                task,
                current_stage="requirement_analysis",
                stage_status="running",
                requirement_analysis_json=requirement_analysis_output,
                case_names_json="",
                detailed_cases_json=EMPTY_CASES_JSON,
            )
        )

    def _report_case_names(
        self,
        task: Task,
        progress_callback,
        stage_state: dict[str, str],
        case_names_output: str,
    ) -> None:
        """记录 case_names 产物并上报 progress。"""

        stage_state["case_names_json"] = case_names_output
        progress_callback(
            build_progress(
                task,
                current_stage="case_names",
                stage_status="running",
                requirement_analysis_json=stage_state["requirement_analysis_json"],
                case_names_json=case_names_output,
                detailed_cases_json=EMPTY_CASES_JSON,
            )
        )

    def _log_execution_context(self, task: Task, *, config_path: str, workspace) -> None:
        credentials = task.payload.llm_credentials
        LOGGER.info(
            "functional task nanobot context: task_id=%s checkpoint=%s document_type=%s "
            "source_chars=%s extra_instruction_chars=%s has_credentials=%s model=%s base_url=%s "
            "workspace=%s config_path=%s",
            task.task_id,
            task.checkpoint_enabled,
            _resolve_functional_document_type(task),
            len(task.payload.source_content or ""),
            len(task.payload.extra_instruction or ""),
            credentials is not None,
            credentials.model if credentials is not None else "",
            credentials.base_url if credentials is not None else "",
            workspace,
            config_path,
        )
