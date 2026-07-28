"""Requirement-analysis source file downloader."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlparse

from testing_agent_ai_worker.models.task import Task
from testing_agent_ai_worker.platform.http_client import PlatformHttpClient


class RequirementSourceDownloader(Protocol):
    def download_source(
        self,
        *,
        document_download_url: str,
        document_type: str,
        task: Task,
        workspace: Path,
    ) -> Path: ...


@dataclass(slots=True)
class PlatformRequirementSourceDownloader:
    client: PlatformHttpClient

    def download_source(
        self,
        *,
        document_download_url: str,
        document_type: str,
        task: Task,
        workspace: Path,
    ) -> Path:
        if not document_download_url.strip():
            raise ValueError("requirement_analysis documentDownloadUrl 不能为空")

        file_bytes = self.client.get_bytes(document_download_url)
        target_dir = workspace / "inputs" / _safe_path_part(task.task_id or "task")
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / _filename_from_url(document_download_url, document_type)
        target_path.write_bytes(file_bytes)
        return target_path


def _filename_from_url(source_url: str, document_type: str) -> str:
    parsed = urlparse(source_url)
    filename = Path(unquote(parsed.path)).name
    if not filename or "." not in filename:
        filename = f"source{_default_suffix(document_type)}"
    return _safe_filename(filename)


def _default_suffix(document_type: str) -> str:
    normalized = document_type.strip().lower()
    if normalized == "word":
        return ".docx"
    return ".txt"


def _safe_filename(filename: str) -> str:
    path = Path(filename)
    suffix = path.suffix if re.fullmatch(r"\.[A-Za-z0-9]+", path.suffix) else ""
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", path.stem).strip("_")
    if not stem:
        stem = "source"
    if not suffix:
        suffix = ".txt"
    return f"{stem}{suffix}"


def _safe_path_part(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return sanitized or "task"
