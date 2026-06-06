"""Profile-driven background scheduler for the belzakupki worker.

Runs as a single daemon thread inside the worker process.  The API
process is completely unaware of it and remains stateless.

Architecture
------------
* One thread polls the DB every ``POLL_INTERVAL_SECONDS`` (default 60).
* For each active profile whose ``last_run_at`` is overdue it spawns a
  *separate* daemon thread so slow ingestions don't block each other.
* Profile's ``last_run_at`` is stamped **before** the run starts, which
  prevents double-triggering even if the run takes longer than the
  interval.

Environment variables
---------------------
SCHEDULER_POLL_INTERVAL   Seconds between DB polls (default: 60).
SCHEDULER_MAX_WORKERS     Max concurrent profile-worker threads (default: 4).
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone

from loguru import logger

_POLL_INTERVAL = int(os.getenv("SCHEDULER_POLL_INTERVAL", "60"))
_MAX_WORKERS = int(os.getenv("SCHEDULER_MAX_WORKERS", "4"))
_last_results_check_time = 0.0
_last_feed_ingest_time = 0.0

# Semaphore limits concurrent per-profile threads so we can't saturate
# resources with dozens of profiles all triggering at the same moment.
_semaphore = threading.BoundedSemaphore(_MAX_WORKERS)


def _parse_interval_seconds(interval_str: str) -> int | None:
    """Convert '1h' / '4h' / '24h' / '30m' to seconds. Returns None on failure."""
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
    logger.error(f"Scheduler: cannot parse interval string '{interval_str}'")
    return None


def _run_profile(profile_id: int) -> None:
    """Ingest + AI-analysis + notify for a single profile. Runs in its own thread."""
    with _semaphore:
        logger.info(f"Scheduler: starting run for profile ID {profile_id}")
        try:
            from belzakupki_db.session import SessionLocal
            from belzakupki_db.models import SearchProfile
            from worker.ingest import (
                ingest_goszakupki_tenders,
                ingest_icetrade_tenders,
                ingest_butb_tenders,
                ingest_gias_tenders,
                run_ai_analysis_for_new_matches,
            )
            from worker.notifications import dispatch_notifications

            with SessionLocal() as session:
                profile = (
                    session.query(SearchProfile)
                    .filter(SearchProfile.id == profile_id)
                    .one_or_none()
                )
                if not profile or not profile.is_active:
                    logger.warning(
                        f"Scheduler: profile {profile_id} not active/found — skipping."
                    )
                    return

                # 1. Ingest from all sources
                logger.info(
                    f"Scheduler: ingesting tenders for profile '{profile.name}' (id={profile_id})"
                )
                ingest_goszakupki_tenders(session, profiles=[profile], limit=20)
                ingest_icetrade_tenders(session, profiles=[profile], limit=20)
                ingest_butb_tenders(session, profiles=[profile], limit=20)
                ingest_gias_tenders(session, profiles=[profile], limit=20)
                session.commit()

                # 2. AI analysis
                logger.info("Scheduler: running AI analysis for new matches")
                run_ai_analysis_for_new_matches(session, "goszakupki_by")
                run_ai_analysis_for_new_matches(session, "icetrade_by")
                run_ai_analysis_for_new_matches(session, "butb_by")
                run_ai_analysis_for_new_matches(session, "gias_by")
                session.commit()

                # 3. Notifications
                logger.info("Scheduler: dispatching notifications")
                dispatch_notifications(session)
                session.commit()

            logger.info(f"Scheduler: profile {profile_id} run finished successfully")
        except Exception:
            logger.exception(f"Scheduler: error during run for profile {profile_id}")


def _scheduler_loop() -> None:
    """Main loop — runs forever inside a daemon thread."""
    from belzakupki_db.session import SessionLocal
    from belzakupki_db.models import SearchProfile

    logger.info(
        f"Scheduler thread started (poll_interval={_POLL_INTERVAL}s, "
        f"max_workers={_MAX_WORKERS})"
    )

    global _last_results_check_time, _last_feed_ingest_time

    while True:
        try:
            # Periodic results check (every 1 hour)
            now_ts = time.time()
            if now_ts - _last_results_check_time >= 3600:
                _last_results_check_time = now_ts
                
                def run_results_check():
                    logger.info("Scheduler: starting periodic results check in background thread")
                    try:
                        from worker.ingest import check_results_for_active_tenders
                        with SessionLocal() as session:
                            check_results_for_active_tenders(session)
                    except Exception:
                        logger.exception("Scheduler: error during periodic results check")
                
                threading.Thread(target=run_results_check, daemon=True, name="scheduler-results-check").start()

            # Periodic centralized feed crawl / ingest (every 30 minutes)
            if now_ts - _last_feed_ingest_time >= 1800:
                _last_feed_ingest_time = now_ts
                
                def run_global_ingest():
                    logger.info("Scheduler: starting periodic centralized feed ingest in background thread")
                    try:
                        from worker.tasks import run_ingest_task_job
                        run_ingest_task_job(tenant_id=None)
                    except Exception:
                        logger.exception("Scheduler: error during periodic centralized feed ingest")
                        
                threading.Thread(target=run_global_ingest, daemon=True, name="scheduler-global-ingest").start()

            with SessionLocal() as session:
                profiles = (
                    session.query(SearchProfile)
                    .filter(
                        SearchProfile.is_active.is_(True),
                        SearchProfile.schedule_interval.isnot(None),
                        SearchProfile.schedule_interval != "manual",
                    )
                    .all()
                )

                now = datetime.now(timezone.utc)

                for profile in profiles:
                    seconds = _parse_interval_seconds(profile.schedule_interval or "")
                    if seconds is None:
                        continue

                    last_run = profile.last_run_at
                    if last_run is not None and last_run.tzinfo is None:
                        last_run = last_run.replace(tzinfo=timezone.utc)

                    should_run = (last_run is None) or (
                        (now - last_run).total_seconds() >= seconds
                    )

                    if not should_run:
                        continue

                    logger.info(
                        f"Scheduler: profile '{profile.name}' (id={profile.id}) "
                        f"is due (last_run={profile.last_run_at})"
                    )

                    # Stamp last_run_at BEFORE spawning to avoid double-trigger
                    profile.last_run_at = now
                    session.add(profile)
                    session.commit()

                    thread = threading.Thread(
                        target=_run_profile,
                        args=(profile.id,),
                        daemon=True,
                        name=f"scheduler-profile-{profile.id}",
                    )
                    thread.start()

        except Exception:
            logger.exception("Scheduler: error in poll loop")

        time.sleep(_POLL_INTERVAL)


# Public API ----------------------------------------------------------------

_scheduler_thread: threading.Thread | None = None
_started = False
_lock = threading.Lock()


def start_scheduler() -> None:
    """Start the scheduler daemon thread (idempotent — safe to call multiple times)."""
    global _scheduler_thread, _started

    with _lock:
        if _started:
            logger.debug("Scheduler already running — ignoring duplicate start() call.")
            return

        _scheduler_thread = threading.Thread(
            target=_scheduler_loop,
            daemon=True,
            name="belzakupki-scheduler",
        )
        _scheduler_thread.start()
        _started = True
        logger.info("Scheduler daemon thread started.")
