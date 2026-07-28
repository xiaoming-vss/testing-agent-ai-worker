"""Nanobot runtime directory helpers.

调用链路：
- task executors 用它解析 task 运行时 workspace 目录
- `nanobot_runtime.config_builder` 用它解析临时配置输出目录

这里把运行期目录约定统一收口到 `runtime_root` 下，避免各处自己拼路径。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from testing_agent_ai_worker.config.models import NanobotConfig
from testing_agent_ai_worker.models.task import Task


DEFAULT_RUNTIME_ROOT = Path(__file__).resolve().parents[3] / "runtime" / "nanobot"


@dataclass(frozen=True, slots=True)
class NanobotRuntimePaths:
    runtime_root: Path
    workspaces_dir: Path
    skills_dir: Path
    temp_configs_dir: Path


def resolve_runtime_paths(nanobot_config: NanobotConfig) -> NanobotRuntimePaths:
    runtime_root = Path(nanobot_config.runtime_root) if nanobot_config.runtime_root else DEFAULT_RUNTIME_ROOT
    return NanobotRuntimePaths(
        runtime_root=runtime_root,
        workspaces_dir=runtime_root / "workspaces",
        skills_dir=runtime_root / "skills",
        temp_configs_dir=runtime_root / "temp-configs",
    )


def resolve_task_workspace(nanobot_config: NanobotConfig, task: Task) -> Path:
    runtime_paths = resolve_runtime_paths(nanobot_config)
    workspace_key = task.project_id.strip() or f"task-{task.task_id}"
    return runtime_paths.workspaces_dir / f"project-{workspace_key}"
