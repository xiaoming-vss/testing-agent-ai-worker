"""Shared logging initialization for the worker process."""

from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from testing_agent_ai_worker.config.models import LoggingConfig


def setup_logging(
    config: LoggingConfig,
    *,
    base_dir: str | Path | None = None,
) -> logging.Logger:
    logger = logging.getLogger("testing_agent_ai_worker")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    logger.setLevel(getattr(logging, config.level.upper(), logging.INFO))
    logger.propagate = False

    resolved_base_dir = Path(base_dir or ".")
    log_dir = resolved_base_dir / config.dir
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = TimedRotatingFileHandler(
        log_dir / config.filename,
        when="midnight",
        backupCount=config.retention_days,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if config.console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger
