"""Backward-compatible imports for nanobot config helpers."""

from __future__ import annotations

from contextlib import contextmanager

from testing_agent_ai_worker.config.models import NanobotConfig
from testing_agent_ai_worker.models.task import Task
from testing_agent_ai_worker.nanobot_runtime import config_builder as _runtime

DEFAULT_TEMPLATE_PATH = _runtime.DEFAULT_TEMPLATE_PATH
_load_template_config = _runtime._load_template_config
_overlay_llm_credentials = _runtime._overlay_llm_credentials


@contextmanager
def task_config_path(*, nanobot_config: NanobotConfig, task: Task):
    """Compatibility wrapper that preserves patching `DEFAULT_TEMPLATE_PATH`."""

    original_template_path = _runtime.DEFAULT_TEMPLATE_PATH
    _runtime.DEFAULT_TEMPLATE_PATH = DEFAULT_TEMPLATE_PATH
    try:
        with _runtime.task_config_path(nanobot_config=nanobot_config, task=task) as config_path:
            yield config_path
    finally:
        _runtime.DEFAULT_TEMPLATE_PATH = original_template_path
