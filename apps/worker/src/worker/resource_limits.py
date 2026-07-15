"""Small resource-safety primitives shared by worker background jobs."""
from __future__ import annotations

from collections.abc import Callable
import os
import queue
import threading
from typing import Any

from loguru import logger


def positive_int_env(name: str, default: int) -> int:
    """Read a strictly positive integer without making startup fragile."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        logger.warning("{} must be an integer; using default {}", name, default)
        return default
    if value < 1:
        logger.warning("{} must be positive; using default {}", name, default)
        return default
    return value


class BoundedTaskExecutor:
    """Run a bounded number of unique tasks with a bounded waiting queue.

    A fixed daemon worker pool consumes a bounded queue while the key set
    prevents repeated scheduler polls from overlapping the same job.
    """

    def __init__(self, *, max_workers: int, max_pending: int) -> None:
        self._queue: queue.Queue[
            tuple[str, Callable[..., Any], tuple[Any, ...]] | None
        ] = queue.Queue(maxsize=max_pending)
        self._active_keys: set[str] = set()
        self._lock = threading.Lock()
        self._workers = [
            threading.Thread(
                target=self._worker_loop,
                daemon=True,
                name=f"belzakupki-scheduled-{index + 1}",
            )
            for index in range(max_workers)
        ]
        for worker in self._workers:
            worker.start()

    def submit(self, key: str, function: Callable[..., Any], *args: Any) -> bool:
        """Submit work if its key is idle and bounded capacity is available."""
        with self._lock:
            if key in self._active_keys:
                return False
            self._active_keys.add(key)
            try:
                self._queue.put_nowait((key, function, args))
            except queue.Full:
                self._active_keys.remove(key)
                return False
        return True

    def _worker_loop(self) -> None:
        while True:
            task = self._queue.get()
            if task is None:
                self._queue.task_done()
                return
            key, function, args = task
            try:
                self._run(key, function, args)
            except Exception:
                logger.exception("Scheduled task {} failed", key)
            finally:
                self._queue.task_done()

    def _run(
        self,
        key: str,
        function: Callable[..., Any],
        args: tuple[Any, ...],
    ) -> None:
        try:
            function(*args)
        finally:
            with self._lock:
                self._active_keys.remove(key)

    def shutdown(self, *, wait: bool = True) -> None:
        """Release executor threads; intended for orderly shutdown and tests."""
        if wait:
            self._queue.join()
        for _ in self._workers:
            self._queue.put(None)
        if wait:
            for worker in self._workers:
                worker.join()
