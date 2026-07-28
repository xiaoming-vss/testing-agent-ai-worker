"""Worker entrypoint."""

from __future__ import annotations

from pathlib import Path

from testing_agent_ai_worker.app.bootstrap import (
    build_task_poller,
    build_task_runner,
    run_poll_once,
    run_worker,
)
from testing_agent_ai_worker.config.loader import load_settings
from testing_agent_ai_worker.logging.setup import setup_logging

__all__ = [
    "build_task_poller",
    "build_task_runner",
    "main",
    "run_poll_once",
    "run_worker",
]


def main(config_path: str | Path | None = None) -> int:
    """CLI 入口。"""

    settings = load_settings(config_path)
    setup_logging(settings.logging)
    return run_worker(settings=settings)
