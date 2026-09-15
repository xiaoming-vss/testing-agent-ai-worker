"""Load worker settings from a TOML file."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from testing_agent_ai_worker.config.models import Settings

DEFAULT_CONFIG_PATH = Path("config/worker.toml")


def load_settings(config_path: str | Path | None = None) -> Settings:
    resolved_path = Path(config_path or DEFAULT_CONFIG_PATH)
    with resolved_path.open("rb") as config_file:
        payload: dict[str, Any] = tomllib.load(config_file)
    settings = Settings.model_validate(payload)
    platform_updates = {
        field_name: value
        for field_name, environment_name in {
            "base_url": "TESTING_AGENT_PLATFORM_BASE_URL",
            "worker_token": "TESTING_AGENT_WORKER_TOKEN",
        }.items()
        if (value := os.getenv(environment_name)) is not None
    }
    runtime_root = os.getenv("TESTING_AGENT_NANOBOT_RUNTIME_ROOT")
    nanobot_updates = {"runtime_root": runtime_root} if runtime_root is not None else {}
    return settings.model_copy(
        update={
            "platform": settings.platform.model_copy(update=platform_updates),
            "nanobot": settings.nanobot.model_copy(update=nanobot_updates),
        }
    )
