"""Long-running polling loop helpers.

调用链路：
- `main.run_worker -> run_worker_loop`
- `run_worker_loop -> run_iteration -> _run_worker_iteration`

这里不处理业务，只处理“跑一轮、是否退出、是否休眠”的循环控制。
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from testing_agent_ai_worker.config.models import Settings
from testing_agent_ai_worker.platform.errors import TaskSourceError
from testing_agent_ai_worker.worker.poller import TaskPoller


def run_worker_loop(
    *,
    settings: Settings,
    poller: TaskPoller,
    run_iteration: Callable[[], bool],
    sleep: Callable[[int], None] = time.sleep,
    logger: logging.Logger | None = None,
    max_iterations: int | None = None,
) -> int:
    """运行 worker 主循环。

    `run_iteration` 由上层注入,返回本轮是否认领到任务,方便在单元测试中替换成假实现。
    """

    iterations = 0
    while True:
        try:
            claimed = run_iteration()
        except TaskSourceError as exc:
            if logger is not None:
                logger.warning("platform task polling unavailable: %s", exc)
            claimed = False
        iterations += 1

        # run_once 语义是「认领一批并排空」:本轮没有认领(队列空或槽位满)即收尾。
        if settings.worker.run_once and not claimed:
            return 0
        if max_iterations is not None and iterations >= max_iterations:
            return 0

        if logger is not None:
            logger.info(
                "worker sleeping for next poll interval: %ss",
                settings.worker.poll_interval_seconds,
            )
        sleep(settings.worker.poll_interval_seconds)
