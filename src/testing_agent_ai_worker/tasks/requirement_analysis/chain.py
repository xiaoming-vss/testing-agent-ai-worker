"""Requirement analysis nanobot chain."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from testing_agent_ai_worker.nanobot_runtime.prompt import build_skill_message


def _default_from_config(**kwargs: Any) -> Any:
    """延迟导入 nanobot，避免单元测试在无 SDK 环境下提前失败。"""

    from nanobot import Nanobot

    return Nanobot.from_config(**kwargs)


@dataclass(slots=True)
class RequirementAnalysisChainRunResult:
    first_step_output: str
    second_step_output: str
    final_output: str


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
    """执行需求分析单步 skill。"""

    factory = from_config or _default_from_config

    async with factory(config_path=config_path, workspace=workspace) as bot:
        result = await bot.run(
            build_skill_message(
                skill_name=skill_name,
                body_text=input_text,
                extra_instruction=extra_instruction,
            ),
            session_key=session_key,
        )
    return result.content


async def run_requirement_analysis_chain(
    *,
    source_text: str,
    session_key: str,
    first_skill_name: str,
    second_skill_name: str,
    third_skill_name: str,
    config_path: str | None = None,
    workspace: str | None = None,
    extra_instruction: str = "",
    on_first_step_result: Callable[[str], None] | None = None,
    on_second_step_result: Callable[[str], None] | None = None,
    from_config: Callable[..., Any] | None = None,
) -> RequirementAnalysisChainRunResult:
    """执行需求分析的三段 skill 链。"""

    factory = from_config or _default_from_config

    async with factory(config_path=config_path, workspace=workspace) as bot:
        first_result = await bot.run(
            build_skill_message(
                skill_name=first_skill_name,
                body_text=source_text,
                extra_instruction=extra_instruction,
            ),
            session_key=session_key,
        )
        if on_first_step_result is not None:
            on_first_step_result(first_result.content)

        second_result = await bot.run(
            build_skill_message(
                skill_name=second_skill_name,
                body_text=first_result.content,
                extra_instruction=extra_instruction,
            ),
            session_key=session_key,
        )
        if on_second_step_result is not None:
            on_second_step_result(second_result.content)

        third_result = await bot.run(
            build_skill_message(
                skill_name=third_skill_name,
                body_text=second_result.content,
                extra_instruction=extra_instruction,
            ),
            session_key=session_key,
        )

    return RequirementAnalysisChainRunResult(
        first_step_output=first_result.content,
        second_step_output=second_result.content,
        final_output=third_result.content,
    )
