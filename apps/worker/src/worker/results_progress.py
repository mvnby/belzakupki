"""Durable progress for small, resumable results-maintenance jobs."""
from __future__ import annotations

import json

RESULTS_PROGRESS_KEY = "belzakupki:results-check:progress:v1"
RESULTS_SCAN_INTERVAL_SECONDS = 3600


def read_results_progress(redis) -> dict:
    raw = redis.get(RESULTS_PROGRESS_KEY)
    if raw is None:
        return {"after_id": 0, "through_id": None, "next_scan_at": 0}
    progress = json.loads(raw)
    if not isinstance(progress, dict):
        raise ValueError("Invalid results-check progress")
    after = progress.get("after_id")
    through = progress.get("through_id")
    next_scan = progress.get("next_scan_at")
    if (type(after) is not int or after < 0
            or type(next_scan) is not int or next_scan < 0
            or (through is not None and (type(through) is not int or through < after))):
        raise ValueError("Invalid results-check progress")
    return progress


def save_results_progress(redis, progress: dict) -> None:
    # No TTL: Redis AOF retains progress across scheduler/worker restarts.
    redis.set(RESULTS_PROGRESS_KEY, json.dumps(progress))


def results_check_due(redis, now: float) -> bool:
    return read_results_progress(redis)["next_scan_at"] <= now
