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

from .validation import generate_validated


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
    """构造 analyze-functional-requirements 阶段输出约束。"""

    return append_stage_instruction(extra_instruction, FUNCTIONAL_ANALYSIS_JSON_ONLY_INSTRUCTION)


def _build_functional_case_names_body(*, source_text: str, analysis_json: str) -> str:
    """测试点生成同时接收原始需求及结构化分析，支持独立阶段恢复。"""

    return "\n\n".join(
        [
            "【原始需求】",
            source_text.strip(),
            "【需求分析结果 JSON】",
            analysis_json.strip(),
        ]
    )


def _build_functional_case_names_instruction(extra_instruction: str) -> str:
    """构造 generate-solution-test-points 阶段输出约束。"""

    return append_stage_instruction(extra_instruction, FUNCTIONAL_CASE_NAMES_JSON_ONLY_INSTRUCTION)


def _build_functional_instruction_for_skill(skill_name: str, extra_instruction: str) -> str:
    """按功能链路 skill 名称追加对应输出约束。"""

    if skill_name == "analyze-functional-requirements":
        return _build_functional_analysis_instruction(extra_instruction)
    if skill_name == "generate-solution-test-points":
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

    message = build_skill_message(
        skill_name=skill_name,
        body_text=input_text,
        extra_instruction=_build_functional_instruction_for_skill(skill_name, extra_instruction),
    )
    async with factory(config_path=config_path, workspace=workspace) as bot:
        stage = {
            "analyze-functional-requirements": "requirement_analysis",
            "generate-solution-test-points": "case_names",
        }.get(skill_name)
        if stage is None:
            return (await bot.run(message, session_key=session_key)).content
        return await generate_validated(
            stage=stage,
            inputs=message,
            generate=lambda prompt: bot.run(prompt, session_key=session_key),
        )


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
    resume_stage: str = "",
    prior_analysis: str = "",
    prior_case_names: str = "",
    from_config: Callable[..., Any] | None = None,
) -> FunctionalChainRunResult:
    """执行功能测试用例生成的完整三段链路。"""

    factory = from_config or _default_from_config

    async with factory(config_path=config_path, workspace=workspace) as bot:
        if resume_stage in {"case_names", "detailed_cases"}:
            if not prior_analysis.strip():
                raise ValueError("阶段重试缺少已确认需求分析")
            analysis_result = prior_analysis
        else:
            analysis_result = await generate_validated(
                stage="requirement_analysis",
                generate=lambda prompt: bot.run(prompt, session_key=session_key),
                inputs=build_skill_message(
                    skill_name=analysis_skill_name,
                    body_text=source_text,
                    extra_instruction=_build_functional_analysis_instruction(extra_instruction),
                ),
            )
        if on_requirement_analysis_result is not None and resume_stage not in {
            "case_names",
            "detailed_cases",
        }:
            on_requirement_analysis_result(analysis_result)

        if resume_stage == "detailed_cases":
            if not prior_case_names.strip():
                raise ValueError("阶段重试缺少已确认测试点")
            case_names_result = prior_case_names
        else:
            case_names_result = await generate_validated(
                stage="case_names",
                generate=lambda prompt: bot.run(prompt, session_key=session_key),
                inputs=build_skill_message(
                    skill_name=case_name_skill_name,
                    body_text=_build_functional_case_names_body(
                        source_text=source_text,
                        analysis_json=analysis_result,
                    ),
                    extra_instruction=_build_functional_case_names_instruction(extra_instruction),
                ),
            )
        if on_case_names_result is not None and resume_stage != "detailed_cases":
            on_case_names_result(case_names_result)

        merged_cases: list[Any] = []
        batches = _build_model_batches(case_names_result)
        for index, batch in enumerate(batches, 1):
            detailed_cases_result = await generate_validated(
                stage="detailed_cases",
                module=batch["model_name"],
                batch=index,
                previous_cases=merged_cases,
                generate=lambda prompt: bot.run(prompt, session_key=session_key),
                inputs=build_skill_message(
                    skill_name=detailed_case_skill_name,
                    body_text=_build_functional_detailed_case_body(
                        source_text=source_text,
                        requirement_analysis_json=analysis_result,
                        case_names_json=json.dumps(batch["payload"], ensure_ascii=False),
                    ),
                    extra_instruction=_build_functional_detailed_case_instruction(
                        extra_instruction
                    ),
                ),
            )
            merged_cases.extend(_extract_cases(detailed_cases_result, batch["model_name"]))
            if on_detailed_cases_progress is not None:
                on_detailed_cases_progress(
                    "",
                    batch["model_name"],
                    index,
                    len(batches),
                )

    return FunctionalChainRunResult(
        requirement_analysis_output=analysis_result,
        case_names_output=case_names_result,
        detailed_cases_output=json.dumps({"cases": merged_cases}, ensure_ascii=False),
    )
