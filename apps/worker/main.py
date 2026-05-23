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
    
    bot_thread = threading.Thread(target=start_telegram_bot_listener, daemon=True)
    bot_thread.start()

    redis = build_redis()
    queue = Queue("default", connection=redis)
    worker = Worker([queue])

    print("Starting RQ worker (queue=default)")
    worker.work()


if __name__ == "__main__":
    main()
