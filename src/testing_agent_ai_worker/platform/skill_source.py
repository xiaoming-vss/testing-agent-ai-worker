"""Platform project skill syncing.

调用链路：
- `WorkerRunner.process_task -> task executor -> ProjectSkillSyncer`
- `ProjectSkillSyncer -> PlatformProjectSkillSource.sync_project_skills`

这里把平台返回的项目 skill 包同步到当前 nanobot workspace 的 `skills/` 目录，
使 nanobot 能按 workspace skill 规则加载 `skills/<skill-name>/SKILL.md`。
"""

from __future__ import annotations

import io
import json
import shutil
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from testing_agent_ai_worker.platform.errors import SkillSourceError
from testing_agent_ai_worker.platform.http_client import PlatformHttpClient
from testing_agent_ai_worker.platform.schemas import (
    PlatformProjectSkill,
    PlatformProjectSkillListResponse,
)


class ProjectSkillSyncer(Protocol):
    def sync_project_skills(self, *, project_id: str, workspace: Path) -> None: ...


@dataclass(slots=True)
class PlatformProjectSkillSource:
    client: PlatformHttpClient
    list_path_template: str

    def sync_project_skills(self, *, project_id: str, workspace: Path) -> None:
        """同步项目 skill 包到当前 workspace。

        如果本地 manifest 与平台返回的 `hash/size/version` 一致，并且上次解压出的
        skill 目录仍存在，则跳过下载。
        """

        if not project_id.strip():
            return

        payload = self.client.get(self.list_path_template.format(project_id=project_id))
        response = PlatformProjectSkillListResponse.model_validate(payload or {})

        skills_root = workspace / "skills"
        manifest_root = skills_root / ".platform-skill-packages"
        skills_root.mkdir(parents=True, exist_ok=True)
        manifest_root.mkdir(parents=True, exist_ok=True)

        active_manifest_paths = {
            self._manifest_path(manifest_root, skill_package)
            for skill_package in response.skills
        }
        for skill_package in response.skills:
            if self._is_current(skills_root, manifest_root, skill_package):
                continue
            self._download_and_extract(skills_root, manifest_root, skill_package)
        self._remove_stale_manifests(skills_root, manifest_root, active_manifest_paths)

    def _is_current(
        self,
        skills_root: Path,
        manifest_root: Path,
        skill_package: PlatformProjectSkill,
    ) -> bool:
        manifest_path = self._manifest_path(manifest_root, skill_package)
        if not manifest_path.exists():
            return False

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False

        if manifest.get("hash") != skill_package.hash:
            return False
        if int(manifest.get("size") or 0) != skill_package.size:
            return False
        if int(manifest.get("version") or 0) != skill_package.version:
            return False

        extracted_dirs = manifest.get("extractedSkillDirs", [])
        if not isinstance(extracted_dirs, list) or not extracted_dirs:
            return False
        return all((skills_root / str(dirname)).is_dir() for dirname in extracted_dirs)

    def _download_and_extract(
        self,
        skills_root: Path,
        manifest_root: Path,
        skill_package: PlatformProjectSkill,
    ) -> None:
        if not skill_package.download_url.strip():
            raise SkillSourceError(f"项目 skill 包缺少 downloadUrl: {skill_package.filename}")

        archive_bytes = self.client.get_bytes(skill_package.download_url)
        if skill_package.size and len(archive_bytes) != skill_package.size:
            raise SkillSourceError(
                "项目 skill 包大小不匹配: "
                f"filename={skill_package.filename} expected={skill_package.size} actual={len(archive_bytes)}"
            )

        old_manifest = self._read_manifest(self._manifest_path(manifest_root, skill_package))
        self._remove_old_dirs(skills_root, old_manifest)
        extracted_dirs = self._extract_archive(skills_root, skill_package.filename, archive_bytes)
        if not extracted_dirs:
            raise SkillSourceError(f"项目 skill 包未解压出 skill 目录: {skill_package.filename}")

        self._manifest_path(manifest_root, skill_package).write_text(
            json.dumps(
                {
                    "skillSpaceId": skill_package.skill_space_id,
                    "projectId": skill_package.project_id,
                    "filename": skill_package.filename,
                    "hash": skill_package.hash,
                    "size": skill_package.size,
                    "version": skill_package.version,
                    "extractedSkillDirs": extracted_dirs,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _extract_archive(self, skills_root: Path, filename: str, archive_bytes: bytes) -> list[str]:
        lower_name = filename.lower()
        if lower_name.endswith(".zip"):
            return self._extract_zip(skills_root, archive_bytes)
        if lower_name.endswith(".tar") or lower_name.endswith(".tar.gz") or lower_name.endswith(".tgz"):
            return self._extract_tar(skills_root, archive_bytes)
        raise SkillSourceError(f"不支持的项目 skill 包格式: {filename}")

    def _extract_zip(self, skills_root: Path, archive_bytes: bytes) -> list[str]:
        extracted_dirs: set[str] = set()
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                target_path, top_level_dir = self._safe_target(skills_root, entry.filename)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(archive.read(entry))
                extracted_dirs.add(top_level_dir)
        return sorted(extracted_dirs)

    def _extract_tar(self, skills_root: Path, archive_bytes: bytes) -> list[str]:
        extracted_dirs: set[str] = set()
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as archive:
            for entry in archive.getmembers():
                if not entry.isfile():
                    continue
                target_path, top_level_dir = self._safe_target(skills_root, entry.name)
                source = archive.extractfile(entry)
                if source is None:
                    continue
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(source.read())
                extracted_dirs.add(top_level_dir)
        return sorted(extracted_dirs)

    def _safe_target(self, skills_root: Path, archive_name: str) -> tuple[Path, str]:
        raw_parts = Path(archive_name.replace("\\", "/")).parts
        parts = [part for part in raw_parts if part not in ("", ".")]
        if not parts or any(part == ".." for part in parts):
            raise SkillSourceError(f"项目 skill 包包含非法路径: {archive_name}")
        top_level_dir = parts[0]
        target_path = (skills_root.joinpath(*parts)).resolve()
        resolved_root = skills_root.resolve()
        if not self._is_relative_to(target_path, resolved_root):
            raise SkillSourceError(f"项目 skill 包路径越界: {archive_name}")
        return target_path, top_level_dir

    def _remove_stale_manifests(
        self,
        skills_root: Path,
        manifest_root: Path,
        active_manifest_paths: set[Path],
    ) -> None:
        protected_dirs = self._active_extracted_dirs(active_manifest_paths)
        for manifest_path in manifest_root.glob("*.json"):
            if manifest_path in active_manifest_paths:
                continue
            self._remove_old_dirs(
                skills_root,
                self._read_manifest(manifest_path),
                protected_dirs=protected_dirs,
            )
            manifest_path.unlink(missing_ok=True)

    def _active_extracted_dirs(self, active_manifest_paths: set[Path]) -> set[str]:
        protected_dirs: set[str] = set()
        for manifest_path in active_manifest_paths:
            manifest = self._read_manifest(manifest_path)
            extracted_dirs = manifest.get("extractedSkillDirs", [])
            if not isinstance(extracted_dirs, list):
                continue
            protected_dirs.update(dirname for dirname in extracted_dirs if isinstance(dirname, str))
        return protected_dirs

    def _remove_old_dirs(
        self,
        skills_root: Path,
        manifest: dict[str, Any],
        *,
        protected_dirs: set[str] | None = None,
    ) -> None:
        extracted_dirs = manifest.get("extractedSkillDirs", [])
        if not isinstance(extracted_dirs, list):
            return
        protected = protected_dirs or set()
        resolved_root = skills_root.resolve()
        for dirname in extracted_dirs:
            if not isinstance(dirname, str) or dirname in ("", ".", "..", ".platform-skill-packages"):
                continue
            if dirname in protected:
                continue
            target = (skills_root / dirname).resolve()
            if self._is_relative_to(target, resolved_root) and target.is_dir():
                shutil.rmtree(target)

    @staticmethod
    def _read_manifest(manifest_path: Path) -> dict[str, Any]:
        if not manifest_path.exists():
            return {}
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return manifest if isinstance(manifest, dict) else {}

    @staticmethod
    def _manifest_path(manifest_root: Path, skill_package: PlatformProjectSkill) -> Path:
        filename = Path(skill_package.filename).name or f"{skill_package.skill_space_id}.archive"
        return manifest_root / f"{filename}.json"

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True
