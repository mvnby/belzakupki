"""Durable producer for profile-driven RQ jobs.

The scheduler never executes scraping, OCR, AI, or notification work itself.
All heavy work goes through the single RQ worker execution plane.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from loguru import logger
from redis import Redis
from rq import Queue, Retry
from rq.exceptions import DuplicateJobError

from worker.resource_limits import positive_int_env


POLL_INTERVAL_SECONDS = positive_int_env("SCHEDULER_POLL_INTERVAL", 60)
MAX_PENDING_JOBS = positive_int_env("SCHEDULER_MAX_PENDING", 8)
JOB_TIMEOUT_SECONDS = positive_int_env("SCHEDULER_JOB_TIMEOUT", 3600)
FAILED_JOB_TTL_SECONDS = positive_int_env("SCHEDULER_FAILED_JOB_TTL", 300)


def _parse_interval_seconds(interval_str: str) -> int | None:
    """Convert ``1h`` / ``4h`` / ``24h`` / ``30m`` to seconds."""
    if not interval_str or interval_str == "manual":
        return None
    try:
        if interval_str.endswith("h"):
            return int(interval_str[:-1]) * 3600
        if interval_str.endswith("d"):
            return int(interval_str[:-1]) * 86400
        if interval_str.endswith("m"):
            return int(interval_str[:-1]) * 60
    except ValueError:
        pass
    logger.error("Scheduler: cannot parse interval string '{}'", interval_str)
    return None


def enqueue_scheduled_job(
    queue: Queue,
    *,
    key: str,
    function: str,
    args: tuple[object, ...] = (),
) -> bool:
    """Enqueue one unique bounded job, returning false when it is deferred."""
    if len(queue) >= MAX_PENDING_JOBS:
        logger.warning(
            "Scheduler: queue capacity {} reached; deferring {}",
            MAX_PENDING_JOBS,
            key,
        )
        return False

    try:
        queue.enqueue_call(
            func=function,
            args=args,
            job_id=f"belzakupki-scheduled-{key}",
            unique=True,
            timeout=JOB_TIMEOUT_SECONDS,
            result_ttl=0,
            failure_ttl=FAILED_JOB_TTL_SECONDS,
            retry=Retry(max=3, interval=[60, 300, 900]),
        )
    except DuplicateJobError:
        logger.debug("Scheduler: {} is already queued or running", key)
        return False
    return True


def run_scheduler(*, redis: Redis | None = None) -> None:
    """Poll due work forever and submit it to the default RQ queue."""
    from belzakupki_db.models import SearchProfile
    from belzakupki_db.session import SessionLocal

    connection = redis if redis is not None else Redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0")
    )
    queue = Queue("default", connection=connection)
    last_results_enqueue = 0.0
    last_global_enqueue = 0.0

    logger.info(
        "Scheduler producer started (poll={}s, max_pending={})",
        POLL_INTERVAL_SECONDS,
        MAX_PENDING_JOBS,
    )

    while True:
        try:
            now_ts = time.time()
            if now_ts - last_results_enqueue >= 3600 and enqueue_scheduled_job(
                queue,
                key="results-check",
                function="worker.tasks.run_results_check_task_job",
            ):
                last_results_enqueue = now_ts

            if now_ts - last_global_enqueue >= 1800 and enqueue_scheduled_job(
                queue,
                key="global-ingest",
                function="worker.tasks.run_ingest_task_job",
                args=(None,),
            ):
                last_global_enqueue = now_ts

            with SessionLocal() as session:
                profiles = (
                    session.query(SearchProfile)
                    .filter(
                        SearchProfile.is_active.is_(True),
                        SearchProfile.schedule_interval.isnot(None),
                        SearchProfile.schedule_interval != "manual",
                    )
                    .order_by(SearchProfile.id.asc())
                    .yield_per(100)
                )
                now = datetime.now(timezone.utc)

                for profile in profiles:
                    interval = _parse_interval_seconds(profile.schedule_interval or "")
                    if interval is None:
                        continue

                    last_run = profile.last_run_at
                    if last_run is not None and last_run.tzinfo is None:
                        last_run = last_run.replace(tzinfo=timezone.utc)
                    if last_run is not None and (now - last_run).total_seconds() < interval:
                        continue

                    enqueue_scheduled_job(
                        queue,
                        key=f"profile-{profile.id}",
                        function="worker.tasks.run_profile_task_job",
                        args=(profile.id,),
                    )
                    # ``last_run_at`` is intentionally untouched here. The RQ
                    # job stamps it only after the complete pipeline succeeds.
        except Exception:
            logger.exception("Scheduler: error in producer poll")

        time.sleep(POLL_INTERVAL_SECONDS)
