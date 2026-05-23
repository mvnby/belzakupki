"""Worker process entrypoint.

Starts three concurrent components:
1. Telegram bot listener (daemon thread) — handles callback_query from users.
2. Scheduler (daemon thread) — polls DB and triggers per-profile ingest/notify.
3. RQ worker (main thread) — processes jobs queued via Redis.
"""
from __future__ import annotations

import os

from redis import Redis
from rq import Queue, Worker


def build_redis() -> Redis:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return Redis.from_url(redis_url)


def main() -> None:
    import threading
    from worker.telegram_bot import start_telegram_bot_listener
    from worker.scheduler import start_scheduler

    # — Telegram bot listener
    bot_thread = threading.Thread(
        target=start_telegram_bot_listener,
        daemon=True,
        name="telegram-bot-listener",
    )
    bot_thread.start()

    # — Profile scheduler (replaces the thread-in-API approach)
    start_scheduler()

    # — RQ worker (blocking — keeps the process alive)
    redis = build_redis()
    queue = Queue("default", connection=redis)
    worker = Worker([queue], connection=redis)

    print("Starting RQ worker (queue=default) with integrated scheduler")
    worker.work()


if __name__ == "__main__":
    main()
