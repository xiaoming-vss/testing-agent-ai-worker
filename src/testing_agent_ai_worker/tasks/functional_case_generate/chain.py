"""Functional test case generation nanobot chain."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from testing_agent_ai_worker.nanobot_runtime.prompt import (
    FUNCTIONAL_ANALYSIS_JSON_ONLY_INSTRUCTION,
    FUNCTIONAL_CASE_NAMES_JSON_ONLY_INSTRUCTION,
    append_stage_instruction,
    build_skill_message,
)
from testing_agent_ai_worker.tasks.functional_case_generate.detailed_batches import (
    _build_functional_detailed_case_body,
    _build_functional_detailed_case_instruction,
    _build_model_batches,
    _extract_cases,
)


def _default_from_config(**kwargs: Any) -> Any:
    """延迟导入 nanobot，避免单元测试在无 SDK 环境下提前失败。"""

    from nanobot import Nanobot

    return Nanobot.from_config(**kwargs)


@dataclass(slots=True)
class FunctionalChainRunResult:
    requirement_analysis_output: str
    case_names_output: str
    detailed_cases_output: str


def _build_functional_analysis_instruction(extra_instruction: str) -> str:
    """构造 solution-test-point-analyzer 阶段输出约束。"""

    return append_stage_instruction(extra_instruction, FUNCTIONAL_ANALYSIS_JSON_ONLY_INSTRUCTION)


def _build_functional_case_names_instruction(extra_instruction: str) -> str:
    """构造 test-case-name-extractor 阶段输出约束。"""

    return append_stage_instruction(extra_instruction, FUNCTIONAL_CASE_NAMES_JSON_ONLY_INSTRUCTION)


def _build_functional_instruction_for_skill(skill_name: str, extra_instruction: str) -> str:
    """按功能链路 skill 名称追加对应输出约束。"""

    if skill_name == "solution-test-point-analyzer":
        return _build_functional_analysis_instruction(extra_instruction)
    if skill_name == "test-case-name-extractor":
        return _build_functional_case_names_instruction(extra_instruction)
    return extra_instruction


async def run_skill_step(
    *,
    input_text: str,
    session_key: str,
    skill_name: str,
    config_path: str | None = None,
    workspace: str | None = None,
    extra_instruction: str = "",
    from_config: Callable[..., Any] | None = None,
) -> str:
    """执行单步 skill。"""

    factory = from_config or _default_from_config

    async with factory(config_path=config_path, workspace=workspace) as bot:
        result = await bot.run(
            build_skill_message(
                skill_name=skill_name,
                body_text=input_text,
                extra_instruction=_build_functional_instruction_for_skill(skill_name, extra_instruction),
            ),
            session_key=session_key,
        )
    return result.content


async def run_functional_chain(
    *,
    source_text: str,
    session_key: str,
    analysis_skill_name: str,
    case_name_skill_name: str,
    detailed_case_skill_name: str,
    config_path: str | None = None,
    workspace: str | None = None,
    extra_instruction: str = "",
    on_requirement_analysis_result: Callable[[str], None] | None = None,
    on_case_names_result: Callable[[str], None] | None = None,
    on_detailed_cases_progress: Callable[[str, str, int, int], None] | None = None,
    from_config: Callable[..., Any] | None = None,
) -> FunctionalChainRunResult:
    """执行功能测试用例生成的完整三段链路。"""

    factory = from_config or _default_from_config

    async with factory(config_path=config_path, workspace=workspace) as bot:
        analysis_result = await bot.run(
            build_skill_message(
                skill_name=analysis_skill_name,
                body_text=source_text,
                extra_instruction=_build_functional_analysis_instruction(extra_instruction),
            ),
            session_key=session_key,
        )
        if on_requirement_analysis_result is not None:
            on_requirement_analysis_result(analysis_result.content)

        case_names_result = await bot.run(
            build_skill_message(
                skill_name=case_name_skill_name,
                body_text=analysis_result.content,
                extra_instruction=_build_functional_case_names_instruction(extra_instruction),
            ),
            session_key=session_key,
        )
        if on_case_names_result is not None:
            on_case_names_result(case_names_result.content)

        merged_cases: list[Any] = []
        batches = _build_model_batches(case_names_result.content)
        for index, batch in enumerate(batches, 1):
            detailed_cases_result = await bot.run(
                build_skill_message(
                    skill_name=detailed_case_skill_name,
                    body_text=_build_functional_detailed_case_body(
                        requirement_analysis_json=analysis_result.content,
                        case_names_json=json.dumps(batch["payload"], ensure_ascii=False),
                    ),
                    extra_instruction=_build_functional_detailed_case_instruction(extra_instruction),
                ),
                session_key=session_key,
            )
            merged_cases.extend(_extract_cases(detailed_cases_result.content, batch["model_name"]))
            if on_detailed_cases_progress is not None:
                on_detailed_cases_progress(
                    json.dumps({"cases": merged_cases}, ensure_ascii=False),
                    batch["model_name"],
                    index,
                    len(batches),
                )

    return FunctionalChainRunResult(
        requirement_analysis_output=analysis_result.content,
        case_names_output=case_names_result.content,
        detailed_cases_output=json.dumps({"cases": merged_cases}, ensure_ascii=False),
    )
