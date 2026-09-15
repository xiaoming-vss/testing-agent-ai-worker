"""GitLab direct fetch: build per-repository diff blocks from code bindings.

凭据仅驻内存:每次请求新建 httpx client(仿平台 http 客户端惯例),不落盘、不入日志。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from testing_agent_ai_worker.models.task import GitlabCredentials, RepositoryBinding
from testing_agent_ai_worker.tasks.code_risk_analysis.diff_prep import (
    compute_diffstat,
    filter_diff_files,
)

# Git 空树 SHA(GitLab compare API 无 empty_tree 参数,无基线时以它为 from)。
GIT_EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class GitlabDiffError(RuntimeError):
    """GitLab 拉取失败(网络、鉴权、基线解析等),消息含仓库与补救线索。"""


@dataclass(slots=True)
class GitlabRepoDiff:
    """单个仓库的 diff 区块:元信息 + diffstat + 过滤后的文件级 diff。

    diffstat 基于全部 diff 条目(含被过滤文件),diff_files 为净化后的文件级正文。
    """

    repository_id: str
    branch: str
    baseline_commit: str  # "none" 表示无基线
    head_commit: str
    files_changed: int
    additions: int
    deletions: int
    diff_files: list[dict[str, Any]]


def _is_sha(ref: str) -> bool:
    return bool(_SHA_RE.match(ref))


@dataclass(slots=True)
class GitlabDiffClient:
    """轻量 GitLab API 客户端(PRIVATE-TOKEN 头,网络类异常重试一次)。"""

    base_url: str
    access_token: str
    timeout_seconds: float = 120.0
    transport: httpx.BaseTransport | None = None
    backoff_seconds: float = 2.0

    def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        headers = {"PRIVATE-TOKEN": self.access_token, "Accept": "application/json"}
        with httpx.Client(
            base_url=self.base_url.rstrip("/"),
            timeout=self.timeout_seconds,
            transport=self.transport,
            headers=headers,
        ) as client:
            try:
                response = client.get(path, params=params)
            except httpx.TransportError:
                time.sleep(self.backoff_seconds)
                response = client.get(path, params=params)
            response.raise_for_status()
            if not response.content:
                return {}
            return response.json()

    def compare(self, repository_id: str, *, from_ref: str, to_ref: str) -> dict[str, Any]:
        path = f"/api/v4/projects/{quote(str(repository_id), safe='')}/compare"
        return self._get(path, params={"from": from_ref, "to": to_ref})

    def resolve_commit_sha(self, repository_id: str, ref: str) -> str:
        """解析 ref 为 commit SHA(ref 可能是分支名/tag/SHA)。"""

        path = f"/api/v4/projects/{quote(str(repository_id), safe='')}/repository/commits"
        response = self._get(path, params={"ref_name": ref, "per_page": "1"})
        if not isinstance(response, list) or not response:
            raise GitlabDiffError(f"仓库 {repository_id} ref {ref} 无法解析 commit SHA")
        first = response[0]
        if not isinstance(first, dict) or not first.get("id"):
            raise GitlabDiffError(f"仓库 {repository_id} ref {ref} 无法解析 commit SHA")
        return str(first["id"])


def _resolve_credential(binding: RepositoryBinding, credentials: list[GitlabCredentials]):
    if binding.connection_id:
        return next(
            (c for c in credentials if c.connection_id == binding.connection_id),
            None,
        )
    return next((c for c in credentials if binding.repository_id in c.repository_ids), None)


def _fetch_repo_diff(client: GitlabDiffClient, binding: RepositoryBinding) -> GitlabRepoDiff:
    try:
        from_ref = binding.baseline_ref or GIT_EMPTY_TREE_SHA
        compare = client.compare(binding.repository_id, from_ref=from_ref, to_ref=binding.branch)
        commit = compare.get("commit")
        if not isinstance(commit, dict) or not commit.get("id"):
            raise GitlabDiffError(f"仓库 {binding.repository_id} compare 响应缺少 head commit")
        head_commit = str(commit["id"])
        if binding.baseline_ref:
            # compare.commit 是 to ref 的 head,基线 SHA 按 baseline_ref 单独解析。
            baseline_commit = (
                binding.baseline_ref
                if _is_sha(binding.baseline_ref)
                else client.resolve_commit_sha(binding.repository_id, binding.baseline_ref)
            )
        else:
            baseline_commit = "none"
    except GitlabDiffError:
        raise
    except Exception as exc:
        raise GitlabDiffError(f"仓库 {binding.repository_id} 拉取 diff 失败: {exc}") from exc

    raw_diffs = compare.get("diffs") or []
    if not isinstance(raw_diffs, list):
        raise GitlabDiffError(f"仓库 {binding.repository_id} compare 响应缺少 diffs 列表")
    raw_diff_files = [d for d in raw_diffs if isinstance(d, dict)]
    # diffstat 全量统计(含被过滤文件),文件级正文净化后交付。
    files_changed, additions, deletions = compute_diffstat(raw_diff_files)
    diff_files = filter_diff_files(raw_diff_files)
    return GitlabRepoDiff(
        repository_id=binding.repository_id,
        branch=binding.branch,
        baseline_commit=baseline_commit,
        head_commit=head_commit,
        files_changed=files_changed,
        additions=additions,
        deletions=deletions,
        diff_files=diff_files,
    )


def fetch_repo_diffs(
    *,
    bindings: list[RepositoryBinding],
    credentials: list[GitlabCredentials],
    transport: httpx.BaseTransport | None = None,
    timeout_seconds: float = 120.0,
    backoff_seconds: float = 2.0,
) -> list[GitlabRepoDiff]:
    """逐仓库拉取 diff;任一仓库失败即抛出 GitlabDiffError(fail-fast)。

    同一 connectionId 的绑定共享一个客户端;不同连接各自建 client。
    """

    results: list[GitlabRepoDiff] = []
    clients: dict[str, GitlabDiffClient] = {}
    for binding in bindings:
        if binding.error:
            raise GitlabDiffError(
                f"仓库 {binding.repository_id} 基线解析失败: {binding.error}(请手工指定基线)"
            )
        credential = _resolve_credential(binding, credentials)
        if credential is None:
            raise GitlabDiffError(
                f"仓库 {binding.repository_id} 未匹配到 GitLab 凭据(请重新绑定或检查 PAT)"
            )
        client_key = credential.connection_id or credential.base_url
        client = clients.get(client_key)
        if client is None:
            client = GitlabDiffClient(
                base_url=credential.base_url,
                access_token=credential.access_token,
                timeout_seconds=timeout_seconds,
                transport=transport,
                backoff_seconds=backoff_seconds,
            )
            clients[client_key] = client
        results.append(_fetch_repo_diff(client, binding))
    return results
