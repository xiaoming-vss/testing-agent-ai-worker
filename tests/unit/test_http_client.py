import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from testing_agent_ai_worker.platform.http_client import PlatformHttpClient


class PlatformHttpClientTests(unittest.TestCase):
    def test_headers_use_x_worker_token_name(self) -> None:
        client = PlatformHttpClient(
            base_url="https://platform.example.com",
            worker_token="worker-secret",
        )

        headers = client._headers()

        self.assertEqual(headers["X-Worker-Token"], "worker-secret")
        self.assertNotIn("X-Worker-Key", headers)


if __name__ == "__main__":
    unittest.main()
