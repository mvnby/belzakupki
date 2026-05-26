from __future__ import annotations

import os
from loguru import logger
from redis import Redis

from belzakupki_db.session import SessionLocal
from belzakupki_db.models import SearchProfile
from worker.ingest import ingest_goszakupki_tenders, ingest_icetrade_tenders, ingest_butb_tenders, ingest_gias_tenders, run_ai_analysis_for_new_matches
from worker.routing import run_local_profile_routing
from worker.notifications import dispatch_notifications

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

def get_redis() -> Redis:
    return Redis.from_url(REDIS_URL)

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
            logger.info("RQ Worker: Fetching feeds from goszakupki.by")
            ingest_goszakupki_tenders(session, profiles=None, limit=20)
            logger.info("RQ Worker: Fetching feeds from icetrade.by")
            ingest_icetrade_tenders(session, profiles=None, limit=20)
            logger.info("RQ Worker: Fetching feeds from butb.by")
            ingest_butb_tenders(session, profiles=None, limit=20)
            logger.info("RQ Worker: Fetching feeds from gias.by")
            ingest_gias_tenders(session, profiles=None, limit=20)
            session.commit()
            
            # 2. Local profile routing
            logger.info("RQ Worker: Running local profile routing")
            run_local_profile_routing(session)
            
            # 3. AI scoring / analysis for matched tenders
            logger.info("RQ Worker: Running AI analyses for matches")
            run_ai_analysis_for_new_matches(session, "goszakupki_by")
            run_ai_analysis_for_new_matches(session, "icetrade_by")
            run_ai_analysis_for_new_matches(session, "butb_by")
            run_ai_analysis_for_new_matches(session, "gias_by")
            session.commit()
            
            # 4. Dispatch notifications
            logger.info(f"RQ Worker: Dispatching notifications (tenant_id context: {tenant_id})")
            dispatch_notifications(session, tenant_id=tenant_id)
            session.commit()
            
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
            dispatch_notifications(session, tenant_id=tenant_id)
            session.commit()
        logger.info(f"RQ Worker: Notify task for tenant_id={tenant_id} completed successfully")
    except Exception as e:
        logger.exception(f"RQ Worker: Error during notify task for tenant={tenant_id}: {e}")
        raise e
    finally:
        r.set(status_key, "idle")
