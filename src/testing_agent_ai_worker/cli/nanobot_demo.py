from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable

from testing_agent_ai_worker.nanobot.runner import run_demo


async def run_cli_demo(
    *,
    message: str = "What time is it in Tokyo?",
    session_key: str = "demo:nanobot",
    config_path: str | None = None,
    workspace: str | None = None,
    runner: Callable[..., Awaitable[str]] = run_demo,
    printer: Callable[[str], None] = print,
) -> int:
    content = await runner(
        message=message,
        session_key=session_key,
        config_path=config_path,
        workspace=workspace,
    )
    printer(content)
    return 0


def main() -> int:
    return asyncio.run(run_cli_demo())


if __name__ == "__main__":
    sys.exit(main())
