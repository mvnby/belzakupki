from __future__ import annotations

import os
import time
from functools import partial
from loguru import logger
from redis import Redis

from belzakupki_db.session import SessionLocal
from belzakupki_db.models import SearchProfile
from worker.ingest import (
    get_pending_ai_analysis_max_id,
    get_pending_results_max_id,
    ingest_butb_tenders,
    ingest_gias_tenders,
    ingest_goszakupki_tenders,
    ingest_icetrade_tenders,
    run_ai_analysis_for_new_matches,
    check_results_for_active_tenders,
)
from worker.resource_limits import positive_int_env
from worker.results_progress import (
    read_results_progress, save_results_progress, RESULTS_SCAN_INTERVAL_SECONDS,
)
from worker.routing import (
    get_pending_routing_max_id,
    get_pending_routing_min_id,
    run_local_profile_routing,
)
from worker.notifications import dispatch_notifications

RESULTS_JOB_BATCH_SIZE = positive_int_env("WORKER_RESULTS_JOB_BATCH_SIZE", 5)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

def get_redis() -> Redis:
    return Redis.from_url(REDIS_URL)


class PipelineIncompleteError(RuntimeError):
    """Independent stages completed, but failed stages still need an RQ retry."""


def _run_stage(session, failures: list[str], name: str, operation) -> None:
    """Keep successful work durable and leave a usable session after failure."""
    try:
        operation()
        session.commit()
    except Exception as exc:
        session.rollback()
        failures.append(f"{name}: {exc}")
        logger.exception("RQ Worker: stage {} failed; continuing independent work", name)


def _raise_stage_failures(failures: list[str]) -> None:
    if failures:
        raise PipelineIncompleteError("Pipeline incomplete; failed stages: " + "; ".join(failures))


def _ingest_sources(session, *, profiles) -> list[str]:
    failures: list[str] = []
    for source_code, ingest in (
        ("goszakupki_by", ingest_goszakupki_tenders),
        ("icetrade_by", ingest_icetrade_tenders),
        ("butb_by", ingest_butb_tenders),
        ("gias_by", ingest_gias_tenders),
    ):
        _run_stage(session, failures, f"ingest:{source_code}",
                   partial(ingest, session, profiles=profiles, limit=20, commit=False))
    return failures


def _drain_ai_analysis(session, source_code: str) -> int:
    """Process a stable pending snapshot in bounded, non-starving batches."""
    through_id = get_pending_ai_analysis_max_id(session, source_code)
    if through_id is None:
        return 0

    selected_total = 0
    after_id = 0
    while after_id < through_id:
        batch = run_ai_analysis_for_new_matches(
            session,
            source_code,
            after_id=after_id,
            through_id=through_id,
        )
        if batch.selected_count == 0 or batch.last_selected_id is None:
            break
        if batch.last_selected_id <= after_id:
            raise RuntimeError(
                f"AI analysis cursor did not advance for source {source_code}"
            )

        selected_total += batch.selected_count
        after_id = batch.last_selected_id
        session.commit()
        session.expunge_all()

    return selected_total


def _drain_all_ai_analysis(session) -> None:
    failures: list[str] = []
    for source_code in ("goszakupki_by", "icetrade_by", "butb_by", "gias_by"):
        _run_stage(session, failures, f"ai:{source_code}",
                   partial(_drain_ai_analysis, session, source_code))
    _raise_stage_failures(failures)


def _drain_local_profile_routing(session) -> int:
    """Drain a stable unchecked snapshot; zero matches still count as progress."""
    through_id = get_pending_routing_max_id(session)
    if through_id is None:
        return 0

    matched_total = 0
    pending_id = get_pending_routing_min_id(session, through_id=through_id)
    while pending_id is not None:
        # Each batch commits its checked flags/matches before enrichment.
        matched_total += run_local_profile_routing(session, through_id=through_id)
        session.expunge_all()
        next_pending_id = get_pending_routing_min_id(session, through_id=through_id)
        if next_pending_id is not None and next_pending_id <= pending_id:
            raise RuntimeError("Local routing did not advance its pending cursor")
        pending_id = next_pending_id
    return matched_total


def _drain_results_check(session) -> int:
    """Check each row in a stable results snapshot once per scheduled run."""
    through_id = get_pending_results_max_id(session)
    if through_id is None:
        return 0

    selected_total = 0
    after_id = 0
    while after_id < through_id:
        batch = check_results_for_active_tenders(
            session,
            after_id=after_id,
            through_id=through_id,
        )
        if batch.selected_count == 0 or batch.last_selected_id is None:
            break
        if batch.last_selected_id <= after_id:
            raise RuntimeError("results-check cursor did not advance")

        selected_total += batch.selected_count
        after_id = batch.last_selected_id
        session.expunge_all()

    return selected_total


def run_profile_task_job(profile_id: int) -> None:
    """RQ job: execute one complete profile pipeline sequentially."""
    from datetime import datetime, timezone

    with SessionLocal() as session:
        profile = (
            session.query(SearchProfile)
            .filter(SearchProfile.id == profile_id)
            .one_or_none()
        )
        if not profile or not profile.is_active:
            logger.warning("RQ Worker: profile {} is inactive or missing", profile_id)
            return

        logger.info("RQ Worker: running profile {}", profile_id)
        failures = _ingest_sources(session, profiles=[profile])
        _run_stage(session, failures, "ai", partial(_drain_all_ai_analysis, session))
        _run_stage(session, failures, "notify", partial(dispatch_notifications, session, drain=True))
        _raise_stage_failures(failures)
        # Deterministic RQ job identity prevents overlap while it runs. Stamp
        # completion only after the whole pipeline succeeds so a crash does not
        # postpone this profile for its full schedule interval.
        profile = session.get(SearchProfile, profile_id)
        if profile is None:
            raise RuntimeError(f"profile {profile_id} disappeared during its pipeline")
        profile.last_run_at = datetime.now(timezone.utc)
        session.add(profile)
        session.commit()


def run_results_check_task_job() -> None:
    """Attempt at most one small chunk; persist its cursor only after DB commit."""
    redis = get_redis()
    progress = read_results_progress(redis)
    if progress["next_scan_at"] > time.time():
        return
    with SessionLocal() as session:
        if progress["through_id"] is None:
            progress["through_id"] = get_pending_results_max_id(session)
            progress["after_id"] = 0
            # Freeze the upper boundary before work; retries use the same scan.
            save_results_progress(redis, progress)
        if progress["through_id"] is None:
            progress["next_scan_at"] = int(time.time()) + RESULTS_SCAN_INTERVAL_SECONDS
            save_results_progress(redis, progress)
            return
        batch = check_results_for_active_tenders(
            session,
            after_id=progress["after_id"],
            through_id=progress["through_id"],
            limit=RESULTS_JOB_BATCH_SIZE,
        )
        # The checker commits its writes; this explicit commit also establishes
        # the task's ordering contract before any cursor advancement.
        session.commit()
        if batch.selected_count and (
            batch.last_selected_id is None
            or batch.last_selected_id <= progress["after_id"]
        ):
            raise RuntimeError("results-check cursor did not advance")
        if batch.selected_count == 0 or batch.last_selected_id >= progress["through_id"]:
            progress = {"after_id": 0, "through_id": None,
                        "next_scan_at": int(time.time()) + RESULTS_SCAN_INTERVAL_SECONDS}
        else:
            progress["after_id"] = batch.last_selected_id
        save_results_progress(redis, progress)

def run_ingest_task_job(tenant_id: int | None = None) -> None:
    """RQ Job: Ingests new tenders from all sources for the active profiles of a tenant."""
    logger.info(f"RQ Worker: Starting centralized ingest task (tenant_id context: {tenant_id})")
    r = get_redis()
    
    status_key = f"belzakupki:task:ingest:{tenant_id or 'global'}"
    r.set(status_key, "running")
    
    try:
        with SessionLocal() as session:
            # Check if there are active profiles in the system at all
            active_profiles_count = session.query(SearchProfile).filter(SearchProfile.is_active == True).count()
            if active_profiles_count == 0:
                logger.info("RQ Worker: No active profiles found in the database. Skipping crawl.")
                return
            
            logger.info(f"RQ Worker: Found {active_profiles_count} active profiles in the system. Starting feed crawl...")
            
            # 1. Centralized Ingest (Feed mode, profiles=None)
            failures = _ingest_sources(session, profiles=None)
            
            # 2. Local profile routing
            logger.info("RQ Worker: Running local profile routing")
            _run_stage(session, failures, "routing", partial(_drain_local_profile_routing, session))
            
            # 3. AI scoring / analysis for matched tenders
            logger.info("RQ Worker: Running AI analyses for matches")
            _run_stage(session, failures, "ai", partial(_drain_all_ai_analysis, session))
            
            # 4. Dispatch notifications
            logger.info(f"RQ Worker: Dispatching notifications (tenant_id context: {tenant_id})")
            _run_stage(session, failures, "notify",
                       partial(dispatch_notifications, session, tenant_id=tenant_id, drain=True))
            _raise_stage_failures(failures)
            
        logger.info(f"RQ Worker: Ingest task for tenant_id={tenant_id} completed successfully")
    except Exception as e:
        logger.exception(f"RQ Worker: Error during ingest task for tenant={tenant_id}: {e}")
        raise e
    finally:
        r.set(status_key, "idle")


def run_notify_task_job(tenant_id: int | None = None) -> None:
    """RQ Job: Dispatches notifications for all pending matched tenders."""
    logger.info(f"RQ Worker: Starting manual notify task for tenant_id={tenant_id}")
    r = get_redis()
    
    status_key = f"belzakupki:task:notify:{tenant_id or 'global'}"
    r.set(status_key, "running")
    
    try:
        with SessionLocal() as session:
            # Dispatch only notifications belonging to profiles of this tenant if specified
            dispatch_notifications(session, tenant_id=tenant_id, drain=True)
            session.commit()
        logger.info(f"RQ Worker: Notify task for tenant_id={tenant_id} completed successfully")
    except Exception as e:
        logger.exception(f"RQ Worker: Error during notify task for tenant={tenant_id}: {e}")
        raise e
    finally:
        r.set(status_key, "idle")
