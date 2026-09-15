"""Build task-scoped nanobot configs from platform LLM credentials.

调用链路：
- task executors -> task_config_path

这里把平台下发的 `model/api_key/base_url` 叠加到项目内 nanobot 模板配置，
为每个任务生成一份临时 config，避免污染长期配置文件。
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from testing_agent_ai_worker.config.models import NanobotConfig
from testing_agent_ai_worker.models.task import LlmCredentials, Task
from testing_agent_ai_worker.nanobot_runtime.paths import resolve_runtime_paths

DEFAULT_TEMPLATE_PATH = Path(__file__).resolve().parents[3] / "config" / "nanobot.template.json"


def _load_template_config(template_path: Path) -> dict[str, Any]:
    path = template_path
    if not path.exists():
        raise FileNotFoundError(f"nanobot template not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("nanobot template top-level JSON must be an object")
    return payload


def _overlay_llm_credentials(
    *,
    base_config: dict[str, Any],
    credentials: LlmCredentials,
) -> dict[str, Any]:
    agents = base_config.setdefault("agents", {})
    defaults = agents.setdefault("defaults", {})
    if credentials.model.strip():
        defaults["model"] = credentials.model

    providers = base_config.setdefault("providers", {})
    provider_config = providers.setdefault("custom", {})
    if credentials.api_key.strip():
        provider_config["apiKey"] = credentials.api_key
    if credentials.base_url.strip():
        provider_config["apiBase"] = credentials.base_url
    provider_config.setdefault("apiType", "auto")
    return base_config


@contextmanager
def task_config_path(*, nanobot_config: NanobotConfig, task: Task):
    """返回当前任务应使用的 nanobot config 路径。

    - 无平台凭证：直接复用项目模板
    - 有平台凭证：基于项目模板生成临时文件，并在任务结束后清理
    """

    credentials = task.payload.llm_credentials
    template_path = DEFAULT_TEMPLATE_PATH
    runtime_paths = resolve_runtime_paths(nanobot_config)
    if credentials is None:
        yield str(template_path)
        return

    rendered_config = _overlay_llm_credentials(
        base_config=_load_template_config(template_path),
        credentials=credentials,
    )

    temp_path: str | None = None
    runtime_paths.temp_configs_dir.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        prefix=f"nanobot-task-{task.task_id}-",
        delete=False,
        dir=runtime_paths.temp_configs_dir,
    ) as temp_file:
        json.dump(rendered_config, temp_file, ensure_ascii=False, indent=2)
        temp_path = temp_file.name

    try:
        yield temp_path
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)
