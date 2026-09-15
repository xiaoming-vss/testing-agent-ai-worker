"""Safe download and extraction of UI task source archives."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from zipfile import BadZipFile, ZipFile

from testing_agent_ai_worker.models.task import Task
from testing_agent_ai_worker.platform.http_client import PlatformHttpClient


class SourceArchiveDownloader(Protocol):
    def download_and_extract(
        self, *, source_archive_download_url: str, task: Task, workspace: Path
    ) -> Path: ...


@dataclass(slots=True)
class PlatformSourceArchiveDownloader:
    client: PlatformHttpClient

    def download_and_extract(
        self,
        *,
        source_archive_download_url: str,
        task: Task,
        workspace: Path,
    ) -> Path:
        if not source_archive_download_url.strip():
            raise ValueError("ui_case_generate 缺少 sourceArchiveDownloadUrl")

        try:
            archive_bytes = self.client.get_bytes(source_archive_download_url)
        except Exception as error:
            raise ValueError("sourceArchiveDownloadUrl 下载失败") from error
        source_dir = workspace / "inputs" / _safe_path_part(task.task_id or "task") / "source"
        source_dir.mkdir(parents=True, exist_ok=True)
        try:
            from io import BytesIO

            with ZipFile(BytesIO(archive_bytes)) as archive:
                for member in archive.infolist():
                    target = (source_dir / member.filename).resolve()
                    if not target.is_relative_to(source_dir.resolve()):
                        raise ValueError("source archive contains an unsafe path")
                archive.extractall(source_dir)
        except BadZipFile as error:
            raise ValueError("sourceArchiveDownloadUrl 下载内容不是有效 ZIP") from error

        source_extensions = {".html", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte"}
        if not any(
            path.is_file() and path.suffix.lower() in source_extensions
            for path in source_dir.rglob("*")
        ):
            raise ValueError("source archive 解压后不包含可识别的前端源码")
        return source_dir


def _safe_path_part(value: str) -> str:
    return (
        "".join(char if char.isalnum() or char in "._-" else "_" for char in value).strip("._")
        or "task"
    )
