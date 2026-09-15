from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

from testing_agent_ai_worker.nanobot.runner import ChainRunResult, run_chain

DEFAULT_EXTRACTOR_SKILL_NAME = "openapi-test-config-extractor"
DEFAULT_GENERATOR_SKILL_NAME = "api-cases-yaml-generator"


async def run_chain_demo(
    *,
    openapi_json_path: str,
    session_key: str = "demo:nanobot-chain",
    extractor_skill_name: str = DEFAULT_EXTRACTOR_SKILL_NAME,
    generator_skill_name: str = DEFAULT_GENERATOR_SKILL_NAME,
    config_path: str | None = None,
    workspace: str | None = None,
    extra_instruction: str = "",
    runner: Callable[..., Awaitable[ChainRunResult]] = run_chain,
    printer: Callable[[str], None] = print,
) -> int:
    openapi_text = Path(openapi_json_path).read_text(encoding="utf-8")
    result = await runner(
        openapi_text=openapi_text,
        session_key=session_key,
        extractor_skill_name=extractor_skill_name,
        generator_skill_name=generator_skill_name,
        config_path=config_path,
        workspace=workspace,
        extra_instruction=extra_instruction,
    )
    printer("=== extractor output ===")
    printer(result.extractor_output)
    printer("=== yaml generator output ===")
    printer(result.generator_output)
    return 0


def main(
    *,
    openapi_json_path: str | None = None,
    session_key: str = "demo:nanobot-chain",
    extractor_skill_name: str = DEFAULT_EXTRACTOR_SKILL_NAME,
    generator_skill_name: str = DEFAULT_GENERATOR_SKILL_NAME,
    config_path: str | None = None,
    workspace: str | None = None,
    extra_instruction: str = "",
) -> int:
    if openapi_json_path is None:
        parser = argparse.ArgumentParser(
            description="Generate API cases from an OpenAPI JSON file."
        )
        parser.add_argument("--openapi-json-path", required=True)
        parser.add_argument("--session-key", default=session_key)
        parser.add_argument("--extractor-skill-name", default=extractor_skill_name)
        parser.add_argument("--generator-skill-name", default=generator_skill_name)
        parser.add_argument("--config-path", default=config_path)
        parser.add_argument("--workspace", default=workspace)
        parser.add_argument("--extra-instruction", default=extra_instruction)
        args = parser.parse_args()
        return main(**vars(args))
    return asyncio.run(
        run_chain_demo(
            openapi_json_path=openapi_json_path,
            session_key=session_key,
            extractor_skill_name=extractor_skill_name,
            generator_skill_name=generator_skill_name,
            config_path=config_path,
            workspace=workspace,
            extra_instruction=extra_instruction,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
