"""Worker process entrypoint.

Runs only the sequential RQ consumer. Scheduler and Telegram listener have
separate entrypoints so RQ never forks after application threads are started.
"""
from __future__ import annotations

import os

from redis import Redis
from rq import Queue, Worker


def build_redis() -> Redis:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return Redis.from_url(redis_url)


def main() -> None:
    redis = build_redis()
    queue = Queue("default", connection=redis)
    worker = Worker([queue], connection=redis)

    print("Starting sequential RQ worker (queue=default)")
    # RQ's own scheduler process promotes interval-retry jobs back to the
    # queue. It is not an application thread and starts after Worker setup.
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
