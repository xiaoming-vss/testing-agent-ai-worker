"""Load worker settings from a TOML file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import tomllib

from testing_agent_ai_worker.config.models import Settings


DEFAULT_CONFIG_PATH = Path("config/worker.toml")


def load_settings(config_path: str | Path | None = None) -> Settings:
    resolved_path = Path(config_path or DEFAULT_CONFIG_PATH)
    with resolved_path.open("rb") as config_file:
        payload: dict[str, Any] = tomllib.load(config_file)
    return Settings.model_validate(payload)
