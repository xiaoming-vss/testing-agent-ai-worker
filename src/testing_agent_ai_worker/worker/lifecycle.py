"""Worker polling and heartbeat cadence helpers.

这里集中维护：
- 空闲时多久轮询一次
- heartbeat 间隔如何计算
"""

from __future__ import annotations

import time


class WorkerLifecycle:
    """worker 的轮询与心跳节奏配置对象。"""

    def __init__(
        self,
        *,
        poll_interval_seconds: int,
        heartbeat_interval_seconds: int,
        run_once: bool,
    ) -> None:
        self.poll_interval_seconds = poll_interval_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.run_once = run_once

    def sleep_when_idle(self) -> None:
        """无任务时按轮询间隔休眠。"""

        time.sleep(self.poll_interval_seconds)

    def heartbeat_interval_for(self, lease_seconds: int) -> int:
        """计算 heartbeat 间隔。

        如果显式配置了心跳间隔，则优先使用配置值；
        否则根据平台租约做一个保守估算，尽量在过期前续租。
        """

        if self.heartbeat_interval_seconds > 0:
            return self.heartbeat_interval_seconds
        if lease_seconds <= 2:
            return 1
        return max(1, lease_seconds // 2)
