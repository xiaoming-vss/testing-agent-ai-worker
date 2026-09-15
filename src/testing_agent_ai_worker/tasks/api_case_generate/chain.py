"""API case generation nanobot chain."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from testing_agent_ai_worker.nanobot_runtime.prompt import (
    API_EXTRACTOR_JSON_ONLY_INSTRUCTION,
    API_GENERATOR_YAML_ONLY_INSTRUCTION,
    append_stage_instruction,
    build_skill_message,
)


def _default_from_config(**kwargs: Any) -> Any:
    """延迟导入 nanobot，避免单元测试在无 SDK 环境下提前失败。"""

    from nanobot import Nanobot

    return Nanobot.from_config(**kwargs)


@dataclass(slots=True)
class ChainRunResult:
    extractor_output: str
    generator_output: str


def _build_api_extractor_instruction(extra_instruction: str) -> str:
    """为 OpenAPI 配置提取阶段追加专用 JSON-only 输出约束。"""

    return append_stage_instruction(extra_instruction, API_EXTRACTOR_JSON_ONLY_INSTRUCTION)


def _build_api_generator_instruction(extra_instruction: str) -> str:
    """为 API 用例 YAML 生成阶段追加专用 YAML-only 输出约束。"""

    return append_stage_instruction(extra_instruction, API_GENERATOR_YAML_ONLY_INSTRUCTION)


async def run_chain(
    *,
    openapi_text: str,
    session_key: str,
    extractor_skill_name: str,
    generator_skill_name: str,
    config_path: str | None = None,
    workspace: str | None = None,
    extra_instruction: str = "",
    on_extractor_result: Callable[[str], None] | None = None,
    from_config: Callable[..., Any] | None = None,
) -> ChainRunResult:
    """执行 API 用例生成的两段 skill 链。"""

    factory = from_config or _default_from_config

    async with factory(config_path=config_path, workspace=workspace) as bot:
        extractor_result = await bot.run(
            build_skill_message(
                skill_name=extractor_skill_name,
                body_text=openapi_text,
                extra_instruction=_build_api_extractor_instruction(extra_instruction),
            ),
            session_key=session_key,
        )
        if on_extractor_result is not None:
            on_extractor_result(extractor_result.content)
        generator_result = await bot.run(
            build_skill_message(
                skill_name=generator_skill_name,
                body_text=extractor_result.content,
                extra_instruction=_build_api_generator_instruction(extra_instruction),
            ),
            session_key=session_key,
        )

    return ChainRunResult(
        extractor_output=extractor_result.content,
        generator_output=generator_result.content,
    )
