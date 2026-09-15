"""Requirement analysis checkpoint-stage resume logic."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from testing_agent_ai_worker.models.execution import TaskProgress, TaskResult, TaskStatus
from testing_agent_ai_worker.models.task import Task
from testing_agent_ai_worker.tasks.requirement_analysis.source_downloader import (
    RequirementSourceDownloader,
)
from testing_agent_ai_worker.tasks.result_summary import build_task_result_summary

REQUIREMENT_ANALYSIS_INITIAL_STAGE = "extracting_text"
REQUIREMENT_ANALYSIS_CHECKPOINT_STAGES = {
    "extracting_text",
    "writing_requirement",
    "feature_understanding",
}
REVISION_INSTRUCTION_FIELD = "revisionInstruction"


def execute_checkpoint_task(
    *,
    task: Task,
    started_at: datetime,
    progress_callback,
    config_path: str | None,
    workspace,
    skill_runner,
    source_downloader: RequirementSourceDownloader | None,
    first_skill_name: str,
    second_skill_name: str,
    third_skill_name: str,
) -> TaskResult | None:
    """执行需求分析 checkpoint 模式的阶段恢复。"""

    stage = task.current_stage.strip()
    config = _read_checkpoint_config(task)
    revision_instruction = _optional_config_text(config, REVISION_INSTRUCTION_FIELD).strip()

    if stage == "extracting_text":
        if revision_instruction:
            first_step_output = _require_config_text(config, "firstStepOutput", stage)
            revised_output = _resolve_text_result(
                skill_runner(
                    input_text=_build_revision_input(first_step_output, revision_instruction),
                    session_key=task.nanobot_session_key,
                    skill_name=first_skill_name,
                    config_path=config_path,
                    workspace=str(workspace),
                    extra_instruction=task.payload.extra_instruction,
                )
            )
            progress_callback(
                _build_progress(
                    task,
                    current_stage=stage,
                    stage_status="waiting_review",
                    first_step_output=revised_output,
                )
            )
            return None

        if source_downloader is None:
            raise ValueError("requirement_analysis source_downloader is required")
        source_path = source_downloader.download_source(
            document_download_url=task.payload.document_download_url,
            document_type=task.payload.document_type,
            task=task,
            workspace=workspace,
        )
        first_step_output = _resolve_text_result(
            skill_runner(
                input_text=str(source_path),
                session_key=task.nanobot_session_key,
                skill_name=first_skill_name,
                config_path=config_path,
                workspace=str(workspace),
                extra_instruction=task.payload.extra_instruction,
            )
        )
        progress_callback(
            _build_progress(
                task,
                current_stage=stage,
                stage_status="waiting_review",
                first_step_output=first_step_output,
            )
        )
        return None

    first_step_output = _require_config_text(config, "firstStepOutput", stage)
    if stage == "writing_requirement":
        if revision_instruction:
            second_step_output = _require_config_text(config, "secondStepOutput", stage)
            revised_output = _resolve_text_result(
                skill_runner(
                    input_text=_build_revision_input(second_step_output, revision_instruction),
                    session_key=task.nanobot_session_key,
                    skill_name=second_skill_name,
                    config_path=config_path,
                    workspace=str(workspace),
                    extra_instruction=task.payload.extra_instruction,
                )
            )
            progress_callback(
                _build_progress(
                    task,
                    current_stage=stage,
                    stage_status="waiting_review",
                    first_step_output=first_step_output,
                    second_step_output=revised_output,
                )
            )
            return None

        second_step_output = _resolve_text_result(
            skill_runner(
                input_text=first_step_output,
                session_key=task.nanobot_session_key,
                skill_name=second_skill_name,
                config_path=config_path,
                workspace=str(workspace),
                extra_instruction=task.payload.extra_instruction,
            )
        )
        progress_callback(
            _build_progress(
                task,
                current_stage=stage,
                stage_status="waiting_review",
                first_step_output=first_step_output,
                second_step_output=second_step_output,
            )
        )
        return None

    second_step_output = _require_config_text(config, "secondStepOutput", stage)
    if stage == "feature_understanding":
        input_text = second_step_output
        if revision_instruction:
            input_text = _require_final_output(config, stage)
            input_text = _build_revision_input(input_text, revision_instruction)

        final_output = _resolve_text_result(
            skill_runner(
                input_text=input_text,
                session_key=task.nanobot_session_key,
                skill_name=third_skill_name,
                config_path=config_path,
                workspace=str(workspace),
                extra_instruction=task.payload.extra_instruction,
            )
        )
        config_json = _build_config_json(
            first_step_output=first_step_output,
            second_step_output=second_step_output,
        )
        return TaskResult(
            task_id=task.task_id,
            run_id=task.run_id,
            generate_task_id=task.generate_task_id,
            status=TaskStatus.SUCCESS,
            intermediate_json_text=config_json,
            output_yaml=final_output,
            result_summary_json=_build_result_summary_json(
                task=task,
                status=TaskStatus.SUCCESS,
                config_json=config_json,
                output_yaml=final_output,
                error_message=None,
            ),
            started_at=started_at,
            finished_at=datetime.now().astimezone(),
        )

    return TaskResult(
        task_id=task.task_id,
        run_id=task.run_id,
        generate_task_id=task.generate_task_id,
        status=TaskStatus.FAILED,
        error_message=f"不支持的 currentStage: {stage}",
        started_at=started_at,
        finished_at=datetime.now().astimezone(),
    )


def _resolve_runner_result(result):
    if hasattr(result, "__await__"):
        return asyncio.run(result)
    return result


def _resolve_text_result(result) -> str:
    resolved = _resolve_runner_result(result)
    if not isinstance(resolved, str):
        raise ValueError("stage runner result must be text")
    return resolved


def _read_checkpoint_config(task: Task) -> dict[str, object]:
    if not task.config_json.strip():
        return {}
    parsed = json.loads(task.config_json)
    if not isinstance(parsed, dict):
        raise ValueError("configJson 顶层必须是对象")
    return parsed


def _optional_config_text(config: dict[str, object], field_name: str) -> str:
    value = config.get(field_name, "")
    return value if isinstance(value, str) else ""


def _require_config_text(config: dict[str, object], field_name: str, stage: str) -> str:
    value = config.get(field_name, "")
    if not isinstance(value, str):
        raise ValueError(f"{stage} 阶段 configJson.{field_name} 必须是字符串")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{stage} 阶段缺少 configJson.{field_name}")
    return value


def _require_final_output(config: dict[str, object], stage: str) -> str:
    for field_name in ("resultYaml", "finalOutput"):
        value = _optional_config_text(config, field_name).strip()
        if value:
            return _optional_config_text(config, field_name)
    raise ValueError(f"{stage} 阶段缺少 configJson.resultYaml")


def _build_revision_input(current_output: str, revision_instruction: str) -> str:
    return (
        "这是当前阶段已有输出：\n"
        f"{current_output}\n\n"
        "请根据下面的修改要求重新生成当前阶段结果：\n"
        f"{revision_instruction}\n\n"
        "只返回修改后的完整当前阶段结果，不要解释修改过程。"
    )


def _build_progress(
    task: Task,
    *,
    current_stage: str,
    stage_status: str,
    first_step_output: str,
    second_step_output: str | None = None,
) -> TaskProgress:
    config_json = _build_config_json(
        first_step_output=first_step_output,
        second_step_output=second_step_output,
    )
    return TaskProgress(
        task_id=task.task_id,
        run_id=task.run_id,
        current_stage=current_stage,
        stage_status=stage_status,
        intermediate_json_text=config_json,
        output_yaml="",
        result_summary_json=_build_result_summary_json(
            task=task,
            status=stage_status,
            config_json=config_json,
            output_yaml="",
            error_message=None,
        ),
    )


def _build_config_json(
    *,
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
