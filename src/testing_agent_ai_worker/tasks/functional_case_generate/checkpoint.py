"""Functional checkpoint-stage resume logic."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from testing_agent_ai_worker.models.execution import TaskResult, TaskStatus
from testing_agent_ai_worker.models.task import Task
from testing_agent_ai_worker.tasks.functional_case_generate.chain import (
    _build_functional_analysis_instruction,
    _build_functional_case_names_body,
    _build_functional_case_names_instruction,
)
from testing_agent_ai_worker.tasks.functional_case_generate.summary import (
    build_config_json,
    build_progress,
    build_result_summary_json,
)

EMPTY_CASES_JSON = '{"cases":[]}'


def execute_checkpoint_task(
    *,
    task: Task,
    started_at: datetime,
    progress_callback,
    config_path: str | None,
    workspace,
    skill_runner,
    detailed_batch_runner,
) -> TaskResult | None:
    """执行 checkpoint 模式的阶段恢复。"""

    stage = task.current_stage.strip()
    try:
        config = _read_checkpoint_config(task)
    except ValueError:
        if stage != "requirement_analysis":
            raise
        # Initial analysis historically ignores malformed legacy config.
        config = {}
    revision = _optional_config_json_text(config, "revisionInstruction").strip()

    def revision_input(source: str, field: str) -> str:
        if not revision:
            return source
        current = _require_config_json_text(config, field, stage)
        return f"{source}\n\n【当前阶段产物】\n{current}\n\n【本轮优化要求】\n{revision}\n请输出优化后的完整阶段产物。"

    if stage == "requirement_analysis":
        requirement_analysis_json = _resolve_text_result(
            skill_runner(
                input_text=revision_input(task.payload.source_content, "requirementAnalysis"),
                session_key=task.nanobot_session_key,
                skill_name="analyze-functional-requirements",
                config_path=config_path,
                workspace=str(workspace),
                extra_instruction=_build_functional_analysis_instruction(
                    task.payload.extra_instruction
                ),
            )
        )
        progress_callback(
            build_progress(
                task,
                current_stage=stage,
                stage_status="waiting_review",
                requirement_analysis_json=requirement_analysis_json,
                case_names_json="",
                detailed_cases_json=EMPTY_CASES_JSON,
            )
        )
        return None

    requirement_analysis_json = _require_config_json_text(config, "requirementAnalysis", stage)
    if stage == "case_names":
        case_names_json = _resolve_text_result(
            skill_runner(
                input_text=revision_input(
                    _build_functional_case_names_body(
                        source_text=task.payload.source_content,
                        analysis_json=requirement_analysis_json,
                    ),
                    "caseNames",
                ),
                session_key=task.nanobot_session_key,
                skill_name="generate-solution-test-points",
                config_path=config_path,
                workspace=str(workspace),
                extra_instruction=_build_functional_case_names_instruction(
                    task.payload.extra_instruction
                ),
            )
        )
        progress_callback(
            build_progress(
                task,
                current_stage=stage,
                stage_status="waiting_review",
                requirement_analysis_json=requirement_analysis_json,
                case_names_json=case_names_json,
                detailed_cases_json=EMPTY_CASES_JSON,
            )
        )
        return None

    if stage == "detailed_cases":
        case_names_json = _require_config_json_text(config, "caseNames", stage)
        detailed_cases_json = _resolve_text_result(
            detailed_batch_runner(
                source_text=task.payload.source_content,
                requirement_analysis_json=requirement_analysis_json,
                case_names_json=case_names_json,
                session_key=task.nanobot_session_key,
                skill_name="generate-solution-test-cases",
                config_path=config_path,
                workspace=str(workspace),
                extra_instruction=task.payload.extra_instruction,
                **(
                    {
                        "current_cases_json": _require_config_json_text(
                            config, "resultYaml", stage
                        ),
                        "revision_instruction": revision,
                    }
                    if revision
                    else {}
                ),
                on_progress=lambda accumulated_result, _model_name, _index, _total: (
                    progress_callback(
                        build_progress(
                            task,
                            current_stage=stage,
                            stage_status="running",
                            requirement_analysis_json=requirement_analysis_json,
                            case_names_json=case_names_json,
                            detailed_cases_json=accumulated_result,
                        )
                    )
                ),
            )
        )
        config_json = build_config_json(
            requirement_analysis_json=requirement_analysis_json,
            case_names_json=case_names_json,
        )
        return TaskResult(
            task_id=task.task_id,
            run_id=task.run_id,
            generate_task_id=task.generate_task_id,
            status=TaskStatus.SUCCESS,
            intermediate_json_text=config_json,
            output_yaml=detailed_cases_json,
            result_summary_json=build_result_summary_json(
                task=task,
                status=TaskStatus.SUCCESS,
                config_json=config_json,
                detailed_cases_json=detailed_cases_json,
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


def _optional_config_json_text(config: dict[str, object], field_name: str) -> str:
    value = config.get(field_name)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _require_config_json_text(
    config: dict[str, object],
    field_name: str,
    stage: str,
) -> str:
    value = _optional_config_json_text(config, field_name).strip()
    if not value:
        raise ValueError(f"{stage} 阶段缺少 configJson.{field_name}")
    return value
