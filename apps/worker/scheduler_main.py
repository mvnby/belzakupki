"""Dedicated lightweight scheduler producer entrypoint."""
from worker.scheduler import run_scheduler


if __name__ == "__main__":
    run_scheduler()
