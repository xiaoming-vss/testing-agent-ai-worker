import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from testing_agent_ai_worker.models.task import Task, TaskPayload
from testing_agent_ai_worker.tasks.requirement_analysis.source_downloader import (
    PlatformRequirementSourceDownloader,
)


class FakeClient:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.paths: list[str] = []

    def get_bytes(self, path: str) -> bytes:
        self.paths.append(path)
        return self.content


class PlatformRequirementSourceDownloaderTests(unittest.TestCase):
    def test_download_source_saves_file_under_task_inputs_with_safe_docx_name(self) -> None:
        client = FakeClient(b"docx bytes")
        downloader = PlatformRequirementSourceDownloader(client)
        task = Task(
            task_id="worker-task-1", project_id="project-1", payload=TaskPayload(openapi_content="")
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            saved_path = downloader.download_source(
                document_download_url="/internal/ai-worker/tasks/worker-task-1/requirement-document",
                document_type="word",
                task=task,
                workspace=Path(temp_dir),
            )

            self.assertEqual(
                client.paths, ["/internal/ai-worker/tasks/worker-task-1/requirement-document"]
            )
            self.assertEqual(
                saved_path, Path(temp_dir) / "inputs" / "worker-task-1" / "source.docx"
            )
            self.assertEqual(saved_path.read_bytes(), b"docx bytes")

    def test_download_source_uses_document_type_suffix_when_url_has_no_filename(self) -> None:
        client = FakeClient(b"text bytes")
        downloader = PlatformRequirementSourceDownloader(client)
        task = Task(
            task_id="worker task 2", project_id="project-1", payload=TaskPayload(openapi_content="")
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            saved_path = downloader.download_source(
                document_download_url="/internal/ai-worker/tasks/worker-task-2/requirement-document",
                document_type="text",
                task=task,
                workspace=Path(temp_dir),
            )

            self.assertEqual(saved_path, Path(temp_dir) / "inputs" / "worker_task_2" / "source.txt")
            self.assertEqual(saved_path.read_bytes(), b"text bytes")

    def test_download_source_treats_word_document_type_as_docx(self) -> None:
        client = FakeClient(b"word bytes")
        downloader = PlatformRequirementSourceDownloader(client)
        task = Task(
            task_id="worker-task-3", project_id="project-1", payload=TaskPayload(openapi_content="")
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            saved_path = downloader.download_source(
                document_download_url="/internal/ai-worker/tasks/worker-task-3/requirement-document",
                document_type="word",
                task=task,
                workspace=Path(temp_dir),
            )

            self.assertEqual(
                saved_path, Path(temp_dir) / "inputs" / "worker-task-3" / "source.docx"
            )
            self.assertEqual(saved_path.read_bytes(), b"word bytes")


if __name__ == "__main__":
    unittest.main()
