"""Backward-compatible nanobot runner imports."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from testing_agent_ai_worker.tasks.api_case_generate.chain import ChainRunResult, run_chain
from testing_agent_ai_worker.tasks.functional_case_generate.chain import (
    FunctionalChainRunResult,
    run_functional_chain,
    run_skill_step,
)
from testing_agent_ai_worker.tasks.functional_case_generate.detailed_batches import (
    run_functional_detailed_case_batches,
)
from testing_agent_ai_worker.tasks.requirement_analysis.chain import (
    RequirementAnalysisChainRunResult,
    run_requirement_analysis_chain,
)

__all__ = [
    "ChainRunResult",
    "FunctionalChainRunResult",
    "RequirementAnalysisChainRunResult",
    "run_chain",
    "run_demo",
    "run_functional_chain",
    "run_functional_detailed_case_batches",
    "run_requirement_analysis_chain",
    "run_skill_step",
]


def _default_from_config(**kwargs: Any) -> Any:
    """延迟导入 nanobot，避免单元测试在无 SDK 环境下提前失败。"""

    from nanobot import Nanobot

    return Nanobot.from_config(**kwargs)


async def run_demo(
    *,
    message: str,
    session_key: str,
    config_path: str | None = None,
    workspace: str | None = None,
    from_config: Callable[..., Any] | None = None,
) -> str:
    """运行最小 nanobot demo。"""

    factory = from_config or _default_from_config
    async with factory(config_path=config_path, workspace=workspace) as bot:
        result = await bot.run(message, session_key=session_key)
    return result.content
