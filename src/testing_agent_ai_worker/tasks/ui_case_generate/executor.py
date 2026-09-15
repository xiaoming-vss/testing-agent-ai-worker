"""UI test case generation executor."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from testing_agent_ai_worker.config.models import NanobotConfig
from testing_agent_ai_worker.models.execution import TaskProgress, TaskResult, TaskStatus
from testing_agent_ai_worker.models.task import Task
from testing_agent_ai_worker.nanobot_runtime.config_builder import task_config_path
from testing_agent_ai_worker.nanobot_runtime.paths import (
    resolve_runtime_paths,
    resolve_task_workspace,
)
from testing_agent_ai_worker.tasks.functional_case_generate.chain import run_skill_step
from testing_agent_ai_worker.tasks.result_summary import build_task_result_summary
from testing_agent_ai_worker.tasks.ui_case_generate.source_archive import SourceArchiveDownloader
from testing_agent_ai_worker.worker.runner import TaskExecutor

UI_CASE_SKILL_NAME = "generate-ui-test-case"
UI_CASE_YAML_ONLY_INSTRUCTION = """请分析指定的前端源码目录并生成 UI 自动化测试用例。
源码根目录：{source_root}
始终返回非空 YAML list，即使只有一条用例。每条用例必须包含 name、enabled、stepsJson、orderNo；每个步骤必须包含 orderNo、stepName、keyword、continueOnFailure、enabled。operationValue、locatorType、locatorValue、comparator 必须严格按照 keyword 规则提供。不要输出 Markdown 代码块、解释文字或 JSON。"""


VALID_UI_LOCATOR_TYPES = {
    "css",
    "xpath",
    "text",
    "placeholder",
    "label",
    "test_id",
    "testid",
    "role",
}
VALID_UI_COMPARATORS = {"eq", "contains"}


@dataclass(frozen=True, slots=True)
class UiKeywordRule:
    locator_required: bool
    operation: str = "optional"
    comparator_required: bool = False


UI_KEYWORD_RULES = {
    "open": UiKeywordRule(False, "required"),
    "reload": UiKeywordRule(False),
    "click": UiKeywordRule(True),
    "dblclick": UiKeywordRule(True),
    "input": UiKeywordRule(True, "required"),
    "clear": UiKeywordRule(True, "forbidden"),
    "press": UiKeywordRule(True, "required"),
    "wait_text": UiKeywordRule(True, "required"),
    "assert_text": UiKeywordRule(True, "required", True),
    "assert_visible": UiKeywordRule(True, "required"),
    "assert_url": UiKeywordRule(False, "required", True),
    "screenshot": UiKeywordRule(False, "forbidden"),
    "sleep": UiKeywordRule(False, "required"),
}


def _resolve_text_result(result: Any) -> str:
    resolved = asyncio.run(result) if hasattr(result, "__await__") else result
    if not isinstance(resolved, str):
        raise ValueError("UI 用例技能结果必须为文本")
    return resolved


class UiCaseNanobotExecutor(TaskExecutor):
    """下载前端源码归档并调用 UI 用例生成技能。"""

    def __init__(
        self,
        *,
        nanobot_config: NanobotConfig,
        source_downloader: SourceArchiveDownloader,
        skill_runner=run_skill_step,
        skill_name: str = UI_CASE_SKILL_NAME,
    ) -> None:
        self.nanobot_config = nanobot_config
        self.runtime_paths = resolve_runtime_paths(nanobot_config)
        self.source_downloader = source_downloader
        self.skill_runner = skill_runner
        self.skill_name = skill_name

    def execute(self, task: Task, started_at: datetime, progress_callback) -> TaskResult:
        if task.task_type != "ui_case_generate":
            return self._failure(task, started_at, f"不支持的任务类型: {task.task_type}")

        try:
            workspace = resolve_task_workspace(self.nanobot_config, task)
            source_root = self.source_downloader.download_and_extract(
                source_archive_download_url=task.payload.source_archive_download_url,
                task=task,
                workspace=workspace,
            )
            input_text = UI_CASE_YAML_ONLY_INSTRUCTION.format(source_root=source_root)
            if task.payload.extra_instruction.strip():
                input_text = f"{input_text}\n\n{task.payload.extra_instruction.strip()}"
            progress_callback(self._progress(task, source_root))
            with task_config_path(nanobot_config=self.nanobot_config, task=task) as config_path:
                output_yaml = _resolve_text_result(
                    self.skill_runner(
                        input_text=input_text,
                        session_key=task.nanobot_session_key,
                        skill_name=self.skill_name,
                        config_path=config_path,
                        workspace=str(workspace),
                        extra_instruction="",
                    )
                )
            case_count = _validate_ui_cases_yaml(output_yaml)
            return TaskResult(
                task_id=task.task_id,
                run_id=task.run_id,
                generate_task_id=task.generate_task_id,
                status=TaskStatus.SUCCESS,
                intermediate_json_text=json.dumps(
                    {
                        "sourceArchiveDownloadUrl": task.payload.source_archive_download_url,
                        "sourceRoot": str(source_root),
                        "caseCount": case_count,
                    },
                    ensure_ascii=False,
                ),
                output_yaml=output_yaml,
                result_summary_json=self._summary(task, "success", case_count, None),
                started_at=started_at,
                finished_at=datetime.now().astimezone(),
            )
        except (OSError, ValueError, yaml.YAMLError) as error:
            return self._failure(task, started_at, str(error))

    def _failure(self, task: Task, started_at: datetime, error_message: str) -> TaskResult:
        return TaskResult(
            task_id=task.task_id,
            run_id=task.run_id,
            generate_task_id=task.generate_task_id,
            status=TaskStatus.FAILED,
            error_message=error_message,
            result_summary_json=self._summary(task, "failed", 0, error_message),
            started_at=started_at,
            finished_at=datetime.now().astimezone(),
        )

    @staticmethod
    def _progress(task: Task, source_root: Path) -> TaskProgress:
        return TaskProgress(
            task_id=task.task_id,
            run_id=task.run_id,
            current_stage="ui_case_generating",
            stage_status="running",
            intermediate_json_text=json.dumps({"sourceRoot": str(source_root)}, ensure_ascii=False),
        )

    @staticmethod
    def _summary(task: Task, status: str, case_count: int, error_message: str | None) -> str:
        return build_task_result_summary(
            task=task,
            status=status,
            error_message=error_message,
            details={"caseCount": case_count},
        )


def _validate_ui_cases_yaml(output_yaml: str) -> int:
    parsed = yaml.safe_load(output_yaml)
    if isinstance(parsed, list) and parsed:
        cases = parsed
    else:
        raise ValueError("UI 用例结果顶层必须是非空 YAML list")

    for case_index, case in enumerate(cases, start=1):
        _validate_ui_case(case, case_index)
    return len(cases)


def _validate_ui_case(case: object, case_index: int) -> None:
    if not isinstance(case, dict):
        raise ValueError(f"第 {case_index} 条 UI 用例必须是 mapping")
    required_fields = {"name", "enabled", "stepsJson", "orderNo"}
    if not required_fields.issubset(case):
        raise ValueError(f"第 {case_index} 条 UI 用例缺少必填字段")
    if not isinstance(case["name"], str) or not case["name"].strip():
        raise ValueError(f"第 {case_index} 条 UI 用例 name 必须是非空字符串")
    if not isinstance(case["enabled"], bool):
        raise ValueError(f"第 {case_index} 条 UI 用例 enabled 必须是布尔值")
    if not _is_integer(case["orderNo"]) or case["orderNo"] != case_index:
        raise ValueError("UI 用例 orderNo 必须从 1 开始跨用例连续递增")
    if not isinstance(case["stepsJson"], list):
        raise ValueError(f"第 {case_index} 条 UI 用例 stepsJson 必须是 list")

    for step_index, step in enumerate(case["stepsJson"], start=1):
        _validate_ui_step(step, case_index, step_index)


def _validate_ui_step(step: object, case_index: int, step_index: int) -> None:
    prefix = f"第 {case_index} 条 UI 用例的第 {step_index} 个步骤"
    if not isinstance(step, dict):
        raise ValueError(f"{prefix}必须是 mapping")
    required_fields = {"orderNo", "stepName", "keyword", "continueOnFailure", "enabled"}
    if not required_fields.issubset(step):
        raise ValueError(f"{prefix}缺少必填字段")
    if not _is_integer(step["orderNo"]) or step["orderNo"] != step_index:
        raise ValueError(f"{prefix} orderNo 必须从 1 开始连续递增")
    if not isinstance(step["stepName"], str) or not step["stepName"].strip():
        raise ValueError(f"{prefix} stepName 必须是非空字符串")
    if not isinstance(step["continueOnFailure"], bool):
        raise ValueError(f"{prefix} continueOnFailure 必须是布尔值")
    if not isinstance(step["enabled"], bool):
        raise ValueError(f"{prefix} enabled 必须是布尔值")

    keyword = step["keyword"]
    rule = UI_KEYWORD_RULES.get(keyword) if isinstance(keyword, str) else None
    if rule is None:
        raise ValueError(f"{prefix} keyword 不受支持: {keyword}")

    if rule.locator_required:
        locator_type = step.get("locatorType")
        locator_value = step.get("locatorValue")
        if locator_type not in VALID_UI_LOCATOR_TYPES:
            raise ValueError(f"{prefix} locatorType 不受支持或缺失: {locator_type}")
        if not isinstance(locator_value, str) or not locator_value.strip():
            raise ValueError(f"{prefix} locatorValue 必须是非空字符串")
    elif "locatorType" in step or "locatorValue" in step:
        raise ValueError(f"{prefix} keyword={keyword} 不应包含 locatorType/locatorValue")

    if rule.operation == "required":
        if "operationValue" not in step or step["operationValue"] is None:
            raise ValueError(f"{prefix} keyword={keyword} 必须包含 operationValue")
        if isinstance(step["operationValue"], str) and not step["operationValue"].strip():
            raise ValueError(f"{prefix} operationValue 不能为空")
    elif rule.operation == "forbidden" and "operationValue" in step:
        raise ValueError(f"{prefix} keyword={keyword} 不应包含 operationValue")

    if rule.comparator_required:
        if step.get("comparator") not in VALID_UI_COMPARATORS:
            raise ValueError(f"{prefix} comparator 必须是 eq 或 contains")
    elif "comparator" in step:
        raise ValueError(f"{prefix} keyword={keyword} 不应包含 comparator")


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
