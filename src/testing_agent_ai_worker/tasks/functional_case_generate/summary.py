"""Functional task progress and result summary builders."""

from __future__ import annotations

import json

from testing_agent_ai_worker.models.execution import TaskProgress, TaskStatus
from testing_agent_ai_worker.models.task import Task


def build_progress(
    task: Task,
    *,
    current_stage: str,
    stage_status: str,
    enhanced_text: str,
    requirement_analysis_json: str,
    case_names_json: str,
    detailed_cases_json: str,
) -> TaskProgress:
    """构造功能任务的阶段性 progress 快照。"""

    config_json = build_config_json(
        enhanced_text=enhanced_text,
        requirement_analysis_json=requirement_analysis_json,
        case_names_json=case_names_json,
    )
    return TaskProgress(
        task_id=task.task_id,
        run_id=task.run_id,
        current_stage=current_stage,
        stage_status=stage_status,
        intermediate_json_text=config_json,
        output_yaml=detailed_cases_json,
        result_summary_json=build_result_summary_json(
            task=task,
            status="running",
            config_json=config_json,
            detailed_cases_json=detailed_cases_json,
            error_message=None,
        ),
    )


def build_config_json(
    *,
    enhanced_text: str,
    requirement_analysis_json: str,
    case_names_json: str,
) -> str:
    """统一构造功能任务的 `configJson` 结构。"""

    return json.dumps(
        {
            "enhancedText": enhanced_text,
            "requirementAnalysis": parse_optional_json(requirement_analysis_json),
            "caseNames": parse_optional_json(case_names_json),
        },
        ensure_ascii=False,
        indent=2,
    )


def build_result_summary_json(
    *,
    task: Task,
    status: TaskStatus | str,
    config_json: str,
    detailed_cases_json: str,
    error_message: str | None,
) -> str:
    """构造平台展示用摘要 JSON。"""

    document_type = (task.payload.document_type or task.payload.source_type or "").strip().lower()
    summary = {
        "taskId": task.task_id,
        "runId": task.run_id,
        "generateTaskId": task.generate_task_id,
        "taskType": task.task_type,
        "status": status.value if isinstance(status, TaskStatus) else status,
        "projectId": task.project_id,
        "sprintId": task.sprint_id,
        "requirementId": task.requirement_id,
        "documentType": document_type,
        "sourceType": document_type,
        "caseCount": count_cases(detailed_cases_json),
        "configJsonLength": len(config_json),
        "resultLength": len(detailed_cases_json),
        "errorMessage": error_message or "",
    }
    return json.dumps(summary, ensure_ascii=False)


def parse_optional_json(raw_json_text: str):
    normalized = raw_json_text.strip()
    if not normalized:
        return None
    return json.loads(normalized)


def count_cases(detailed_cases_json: str) -> int:
    if not detailed_cases_json.strip():
        return 0
    try:
        parsed = json.loads(detailed_cases_json)
    except json.JSONDecodeError:
        return 0
    if not isinstance(parsed, dict):
        return 0
    cases = parsed.get("cases", [])
    if not isinstance(cases, list):
        return 0
    return len(cases)
