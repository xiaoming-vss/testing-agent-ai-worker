"""Project metadata and public import naming tests."""

import tomllib
import unittest
from pathlib import Path


class ProjectMetadataTests(unittest.TestCase):
    def test_project_uses_testing_agent_ai_worker_name_and_entrypoint(self) -> None:
        pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
        metadata = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

        self.assertEqual(metadata["project"]["name"], "testing-agent-ai-worker")
        self.assertEqual(
            metadata["project"]["scripts"]["testing-agent-ai-worker"],
            "testing_agent_ai_worker.main:main",
        )
        self.assertEqual(
            metadata["project"]["scripts"]["testing-agent-ai-demo"],
            "testing_agent_ai_worker.cli.nanobot_demo:main",
        )
        self.assertEqual(
            metadata["project"]["scripts"]["testing-agent-ai-chain-demo"],
            "testing_agent_ai_worker.cli.nanobot_chain_demo:main",
        )
        self.assertNotIn("testing-agent-worker", metadata["project"]["scripts"])
        self.assertNotIn("testing-agent-demo", metadata["project"]["scripts"])
        self.assertNotIn("testing-agent-chain-demo", metadata["project"]["scripts"])
        self.assertNotIn("nanobot-worker", metadata["project"]["scripts"])

    def test_testing_agent_ai_worker_package_is_importable(self) -> None:
        import testing_agent_ai_worker

        self.assertIsNotNone(testing_agent_ai_worker)
