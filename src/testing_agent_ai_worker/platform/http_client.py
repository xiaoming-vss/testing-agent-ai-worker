"""Minimal HTTP client wrapper for platform protocol calls.

调用链路：
- `task_source/result_sink -> PlatformHttpClient`
- `post/get/patch` 分别服务于 claim、snapshot、started/progress/completed 等调用
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(slots=True)
class PlatformHttpClient:
    base_url: str
    worker_token: str = ""
    timeout_seconds: float = 60.0

    def _headers(self) -> dict[str, str]:
        """构造平台请求头。

        当前平台 worker 鉴权通过 `X-Worker-Token` 传递。
        """

        headers = {"Content-Type": "application/json"}
        if self.worker_token:
            headers["X-Worker-Token"] = self.worker_token
        return headers

    def post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any] | None:
        """发送 JSON POST 请求并返回解析后的 JSON。"""

        with httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            headers=self._headers(),
        ) as client:
            response = client.post(path, json=json_body)
            response.raise_for_status()
            if not response.content:
                return None
            return response.json()

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """发送 GET 请求并返回解析后的 JSON。"""

        with httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            headers=self._headers(),
        ) as client:
            response = client.get(path, params=params)
            response.raise_for_status()
            if not response.content:
                return None
            return response.json()

    def get_bytes(self, path: str) -> bytes:
        """发送 GET 请求并返回原始二进制内容。"""

        with httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            headers=self._headers(),
        ) as client:
            response = client.get(path)
            response.raise_for_status()
            return response.content

    def patch(self, path: str, json_body: dict[str, Any]) -> dict[str, Any] | None:
        """发送 JSON PATCH 请求并返回解析后的 JSON。"""

        with httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            headers=self._headers(),
        ) as client:
            response = client.patch(path, json=json_body)
            response.raise_for_status()
            if not response.content:
                return None
            return response.json()

    def get_with_retry(
        self,
        path: str,
        max_retries: int = 3,
        backoff_base: float = 1.0,
    ) -> dict[str, Any] | None:
        """为易抖动的只读接口提供简单重试。

        当前主要用于获取 LLM 凭证，避免短时网络问题直接打断任务执行。
        """

        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                return self.get(path)
            except Exception as exc:  # pragma: no cover - runtime/network branch
                last_error = exc
                if attempt == max_retries - 1:
                    break
                time.sleep(backoff_base * (attempt + 1))
        if last_error is not None:
            raise last_error
        return None
