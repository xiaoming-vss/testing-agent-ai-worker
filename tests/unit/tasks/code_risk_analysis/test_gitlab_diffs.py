import sys
import unittest
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import httpx

from testing_agent_ai_worker.models.task import GitlabCredentials, RepositoryBinding
from testing_agent_ai_worker.tasks.code_risk_analysis.diff_prep import (
    compute_diffstat,
    is_filtered_diff_file,
)
from testing_agent_ai_worker.tasks.code_risk_analysis.gitlab_diffs import (
    GIT_EMPTY_TREE_SHA,
    GitlabDiffError,
    fetch_repo_diffs,
)


def _binding(**overrides: Any) -> RepositoryBinding:
    values: dict[str, Any] = {
        "binding_id": "binding-1",
        "repository_id": "repo-1",
        "group_id": "group-1",
        "branch": "feat/login",
        "baseline_ref": "refs/heads/master",
        "error": "",
        "connection_id": "conn-gitlab-1",
    }
    values.update(overrides)
    return RepositoryBinding.model_validate(values)


def _credentials(connection_id: str = "conn-gitlab-1", **overrides: Any) -> GitlabCredentials:
    values: dict[str, Any] = {
        "connection_id": connection_id,
        "base_url": "https://gitlab.example.com",
        "access_token": "token-1",
        "repository_ids": ["repo-1", "repo-2"],
    }
    values.update(overrides)
    return GitlabCredentials(**values)


def _compare_response(*, diff_texts: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    if diff_texts is None:
        diff_texts = [
            (
                "src/app.py",
                "@@ -1,3 +1,4 @@\n-def main():\n+def main() -> None:\n pass\n+ # new line\n",
            ),
            ("package-lock.json", '@@ -1 +1 @@\n-{"lock":0}\n+{"lock":1}\n'),
            ("dist/bundle.js", "@@ -1 +1 @@\n-a\n+b\n"),
            ("static/logo.png", ""),
        ]
    return {
        "commit": {"id": "def456"},
        "commits": [{"id": "def456"}],
        "diffs": [
            {
                "old_path": path,
                "new_path": path,
                "new_file": False,
                "deleted_file": False,
                "renamed_file": False,
                "diff": text,
            }
            for path, text in diff_texts
        ],
    }


def _commits_response(baseline_sha: str = "abc123") -> list[dict[str, Any]]:
    return [{"id": baseline_sha}]


def _handler(transport_requests: list[httpx.Request] | None = None):
    """返回按端点分发的 MockTransport handler(compare 响应 / 基线 resolve 响应)。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if transport_requests is not None:
            transport_requests.append(request)
        if request.url.path.endswith("/compare"):
            return httpx.Response(200, json=_compare_response())
        return httpx.Response(200, json=_commits_response())

    return handler


class _RecordingTransport(httpx.MockTransport):
    def __init__(self, handler) -> None:
        super().__init__(handler)
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return super().handle_request(request)


class GitlabDiffFetcherTests(unittest.TestCase):
    def _fetcher(self, transport: httpx.BaseTransport):
        return fetch_repo_diffs(
            bindings=[_binding()],
            credentials=[_credentials()],
            transport=transport,
            backoff_seconds=0,
        )

    def test_fetch_maps_baseline_and_head_commits_and_filters(self) -> None:
        transport = _RecordingTransport(_handler())

        results = self._fetcher(transport)

        self.assertEqual(1, len(results))
        repo_diff = results[0]
        self.assertEqual("repo-1", repo_diff.repository_id)
        self.assertEqual("feat/login", repo_diff.branch)
        # 基线 ref 需要单独解析为 SHA;head SHA 来自 compare 响应。
        self.assertEqual("abc123", repo_diff.baseline_commit)
        self.assertEqual("def456", repo_diff.head_commit)
        # diffstat 全量(4 个文件),文件级正文只保留 src/app.py。
        self.assertEqual(4, repo_diff.files_changed)
        self.assertEqual(["src/app.py"], [f["new_path"] for f in repo_diff.diff_files])
        self.assertEqual(4, repo_diff.additions)
        self.assertEqual(3, repo_diff.deletions)

    def test_fetch_uses_empty_tree_when_no_baseline(self) -> None:
        seen_paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_paths.append(str(request.url))
            if request.url.path.endswith("/compare"):
                return httpx.Response(200, json=_compare_response())
            raise AssertionError("无基线时不应再解析基线 ref")

        results = fetch_repo_diffs(
            bindings=[_binding(baseline_ref=None)],
            credentials=[_credentials()],
            transport=httpx.MockTransport(handler),
            backoff_seconds=0,
        )

        self.assertEqual(1, len(results))
        repo_diff = results[0]
        self.assertEqual("none", repo_diff.baseline_commit)
        self.assertEqual("def456", repo_diff.head_commit)
        self.assertTrue(any(f"from={GIT_EMPTY_TREE_SHA}" in path for path in seen_paths))

    def test_fetch_fails_when_binding_baseline_resolution_error(self) -> None:
        transport = _RecordingTransport(lambda request: httpx.Response(500, json={}))

        with self.assertRaises(GitlabDiffError) as ctx:
            fetch_repo_diffs(
                bindings=[_binding(error="基线分支已删除")],
                credentials=[_credentials()],
                transport=transport,
                backoff_seconds=0,
            )

        self.assertIn("repo-1", str(ctx.exception))
        self.assertIn("基线分支已删除", str(ctx.exception))
        self.assertEqual([], transport.requests)

    def test_fetch_retries_transport_error_once(self) -> None:
        calls = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["count"] += 1
            if calls["count"] == 1:
                raise httpx.ConnectError("connection refused")
            if request.url.path.endswith("/compare"):
                return httpx.Response(200, json=_compare_response())
            return httpx.Response(200, json=_commits_response())

        results = fetch_repo_diffs(
            bindings=[_binding()],
            credentials=[_credentials()],
            transport=httpx.MockTransport(handler),
            backoff_seconds=0,
        )

        # commits 端点失败一次被重试成功,再调 compare:共 3 次请求。
        self.assertEqual(3, calls["count"])
        self.assertEqual(1, len(results))

    def test_fetch_does_not_retry_http_status_error(self) -> None:
        calls = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["count"] += 1
            return httpx.Response(404, json={"message": "Not Found"})

        with self.assertRaises(GitlabDiffError):
            fetch_repo_diffs(
                bindings=[_binding()],
                credentials=[_credentials()],
                transport=httpx.MockTransport(handler),
                backoff_seconds=0,
            )

        self.assertEqual(1, calls["count"])

    def test_fetch_uses_connection_for_its_bindings(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            request.read()
            token = request.headers.get("PRIVATE-TOKEN")
            assert token is not None
            self.assertEqual("token-1", token)
            if request.url.path.endswith("/compare"):
                return httpx.Response(200, json=_compare_response())
            return httpx.Response(200, json=_commits_response())

        results = fetch_repo_diffs(
            bindings=[_binding(), _binding(binding_id="binding-2", repository_id="repo-2")],
            credentials=[_credentials()],
            transport=httpx.MockTransport(handler),
            backoff_seconds=0,
        )

        self.assertEqual(2, len(results))
        self.assertEqual({"repo-1", "repo-2"}, {r.repository_id for r in results})


class DiffPrepTests(unittest.TestCase):
    def test_compute_diffstat_skips_diff_headers(self) -> None:
        diff_files = [
            {"old_path": "a.py", "new_path": "a.py", "diff": "@@ -1 +1 @@\n-add\n+add2\n+\n"},
            {"old_path": "b.py", "new_path": "b.py", "diff": "@@ -3 +3 @@\n-x\n+y\n"},
        ]

        files, additions, deletions = compute_diffstat(diff_files)

        self.assertEqual(2, files)
        self.assertEqual(3, additions)
        self.assertEqual(2, deletions)

    def test_code_line_containing_binary_word_is_not_filtered(self) -> None:
        self.assertFalse(
            is_filtered_diff_file(
                {
                    "old_path": "src/config.py",
                    "new_path": "src/config.py",
                    "diff": "+binary = True\n",
                }
            )
        )

    def test_null_byte_diff_is_filtered_as_binary(self) -> None:
        self.assertTrue(
            is_filtered_diff_file(
                {"old_path": "data.bin", "new_path": "data.bin", "diff": "\0\0\0"}
            )
        )


if __name__ == "__main__":
    unittest.main()
