import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from testing_agent_ai_worker.platform.skill_source import PlatformProjectSkillSource


def _skill_zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        archive.writestr(
            "openapi-test-config-extractor/SKILL.md",
            "---\nname: openapi-test-config-extractor\n---\n\n提取 OpenAPI 测试配置",
        )
    return buffer.getvalue()


class FakeSkillHttpClient:
    def __init__(self, archive_bytes: bytes, *, empty_after_first_get: bool = False) -> None:
        self.archive_bytes = archive_bytes
        self.empty_after_first_get = empty_after_first_get
        self.get_calls: list[str] = []
        self.download_calls: list[str] = []

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        self.get_calls.append(path)
        if self.empty_after_first_get and len(self.get_calls) > 1:
            return {"skills": []}
        return {
            "skills": [
                {
                    "skillSpaceId": "skill-space-1",
                    "projectId": "project-1",
                    "filename": "testing-skills.zip",
                    "downloadUrl": "/internal/download/testing-skills.zip",
                    "hash": "hash-v1",
                    "size": len(self.archive_bytes),
                    "version": 3,
                }
            ]
        }

    def get_bytes(self, path: str) -> bytes:
        self.download_calls.append(path)
        return self.archive_bytes


class PlatformProjectSkillSourceTests(unittest.TestCase):
    def test_sync_project_skills_downloads_extracts_and_writes_manifest(self) -> None:
        archive_bytes = _skill_zip_bytes()
        client = FakeSkillHttpClient(archive_bytes)
        source = PlatformProjectSkillSource(
            client=client,
            list_path_template="/internal/ai-worker/projects/{project_id}/skills",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "project-project-1"

            source.sync_project_skills(project_id="project-1", workspace=workspace)

            skill_file = workspace / "skills" / "openapi-test-config-extractor" / "SKILL.md"
            manifest_file = workspace / "skills" / ".platform-skill-packages" / "testing-skills.zip.json"
            self.assertTrue(skill_file.exists())
            self.assertIn("提取 OpenAPI 测试配置", skill_file.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            self.assertEqual(manifest["hash"], "hash-v1")
            self.assertEqual(manifest["size"], len(archive_bytes))
            self.assertEqual(manifest["version"], 3)
            self.assertEqual(manifest["extractedSkillDirs"], ["openapi-test-config-extractor"])
            self.assertEqual(client.get_calls, ["/internal/ai-worker/projects/project-1/skills"])
            self.assertEqual(client.download_calls, ["/internal/download/testing-skills.zip"])

    def test_sync_project_skills_removes_platform_managed_dirs_missing_from_platform_list(self) -> None:
        archive_bytes = _skill_zip_bytes()
        client = FakeSkillHttpClient(archive_bytes, empty_after_first_get=True)
        source = PlatformProjectSkillSource(
            client=client,
            list_path_template="/internal/ai-worker/projects/{project_id}/skills",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "project-project-1"
            manual_skill = workspace / "skills" / "manually-managed-skill" / "SKILL.md"
            manual_skill.parent.mkdir(parents=True)
            manual_skill.write_text("manual skill", encoding="utf-8")

            source.sync_project_skills(project_id="project-1", workspace=workspace)
            source.sync_project_skills(project_id="project-1", workspace=workspace)

            platform_skill_dir = workspace / "skills" / "openapi-test-config-extractor"
            manifest_file = workspace / "skills" / ".platform-skill-packages" / "testing-skills.zip.json"
            self.assertFalse(platform_skill_dir.exists())
            self.assertFalse(manifest_file.exists())
            self.assertTrue(manual_skill.exists())

    def test_sync_project_skills_skips_download_when_manifest_file_and_extracted_dir_match(self) -> None:
        archive_bytes = _skill_zip_bytes()
        client = FakeSkillHttpClient(archive_bytes)
        source = PlatformProjectSkillSource(
            client=client,
            list_path_template="/internal/ai-worker/projects/{project_id}/skills",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "project-project-1"
            source.sync_project_skills(project_id="project-1", workspace=workspace)
            source.sync_project_skills(project_id="project-1", workspace=workspace)

            self.assertEqual(client.download_calls, ["/internal/download/testing-skills.zip"])


if __name__ == "__main__":
    unittest.main()
