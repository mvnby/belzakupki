from fastapi import Depends, FastAPI, HTTPException, Query, BackgroundTasks, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
import os
import threading

from belzakupki_db.read import (
    get_tender,
    list_matches,
    list_tenders,
    serialize_match,
    serialize_tender,
)
from belzakupki_db.session import get_session
from belzakupki_db.models import SearchProfile, NotificationChannel, Tender, TenderMatch, NotificationLog
from apps.api.schemas import (
    SearchProfileCreate,
    SearchProfileUpdate,
    SearchProfileResponse,
    NotificationChannelCreate,
    NotificationChannelResponse,
)

app = FastAPI(title="belzakupki")

# Состояние фоновых задач
task_status = {
    "ingest": "idle",
    "notify": "idle",
}
status_lock = threading.Lock()


def run_ingest_task():
    global task_status
    with status_lock:
        if task_status["ingest"] == "running":
            return
        task_status["ingest"] = "running"
    try:
        from belzakupki_db.session import SessionLocal
        from worker.ingest import ingest_goszakupki_tenders, ingest_icetrade_tenders
        with SessionLocal() as session:
            # Считываем активные профили
            profiles = session.query(SearchProfile).filter(SearchProfile.is_active == True).all()
            # Запускаем динамический сбор
            ingest_goszakupki_tenders(session, profiles=profiles, limit=20)
            ingest_icetrade_tenders(session, profiles=profiles, limit=20)
    except Exception as e:
        print(f"Error during background ingest: {e}")
    finally:
        with status_lock:
            task_status["ingest"] = "idle"


def run_notify_task():
    global task_status
    with status_lock:
        if task_status["notify"] == "running":
            return
        task_status["notify"] = "running"
    try:
        from belzakupki_db.session import SessionLocal
        from worker.notifications import dispatch_notifications
        with SessionLocal() as session:
            dispatch_notifications(session)
    except Exception as e:
        print(f"Error during background notify: {e}")
    finally:
        with status_lock:
            task_status["notify"] = "idle"


# --- Раздача Фронтенда ---

@app.get("/", response_class=HTMLResponse)
def read_dashboard():
    file_path = "apps/api/static/index.html"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Frontend HTML file not found")
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/style.css")
def read_style():
    file_path = "apps/api/static/style.css"
    if not os.path.exists(file_path):
        return Response(status_code=404)
    with open(file_path, "r", encoding="utf-8") as f:
        return Response(content=f.read(), media_type="text/css")


@app.get("/app.js")
def read_app_js():
    file_path = "apps/api/static/app.js"
    if not os.path.exists(file_path):
        return Response(status_code=404)
    with open(file_path, "r", encoding="utf-8") as f:
        return Response(content=f.read(), media_type="application/javascript")


# --- Статистика ---

@app.get("/api/stats")
def get_stats(session: Session = Depends(get_session)):
    total_tenders = session.query(func.count(Tender.id)).scalar() or 0
    total_matches = session.query(func.count(TenderMatch.id)).scalar() or 0
    
    new_matches = session.query(func.count(TenderMatch.id)).filter(TenderMatch.status == "new").scalar() or 0
    processed_matches = session.query(func.count(TenderMatch.id)).filter(TenderMatch.status == "processed").scalar() or 0
    expired_matches = session.query(func.count(TenderMatch.id)).filter(TenderMatch.status == "expired").scalar() or 0
    
    sent_logs = session.query(func.count(NotificationLog.id)).filter(NotificationLog.status == "sent").scalar() or 0
    error_logs = session.query(func.count(NotificationLog.id)).filter(NotificationLog.status == "error").scalar() or 0

    return {
        "stats": {
            "total_tenders": total_tenders,
            "total_matches": total_matches,
            "new_matches": new_matches,
            "processed_matches": processed_matches,
            "expired_matches": expired_matches,
            "sent_notifications": sent_logs,
            "error_notifications": error_logs,
        },
        "tasks": task_status
    }


# --- Управление профилями поиска (Search Profiles CRUD) ---

@app.get("/api/profiles", response_model=list[SearchProfileResponse])
def get_profiles(session: Session = Depends(get_session)):
    return session.query(SearchProfile).order_by(SearchProfile.id.asc()).all()


@app.post("/api/profiles", response_model=SearchProfileResponse)
def create_profile(data: SearchProfileCreate, session: Session = Depends(get_session)):
    profile = SearchProfile(
        name=data.name,
        description=data.description,
        keywords=data.keywords,
        negative_keywords=data.negative_keywords,
        regions=data.regions,
        categories=data.categories,
        min_score=data.min_score,
        is_active=data.is_active,
        schedule_interval=None if data.schedule_interval == "manual" else data.schedule_interval,
    )
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


@app.put("/api/profiles/{profile_id}", response_model=SearchProfileResponse)
def update_profile(profile_id: int, data: SearchProfileUpdate, session: Session = Depends(get_session)):
    profile = session.query(SearchProfile).filter(SearchProfile.id == profile_id).one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    
    if data.name is not None:
        profile.name = data.name
    if data.description is not None:
        profile.description = data.description
    if data.keywords is not None:
        profile.keywords = data.keywords
    if data.negative_keywords is not None:
        profile.negative_keywords = data.negative_keywords
    if data.regions is not None:
        profile.regions = data.regions
    if data.categories is not None:
        profile.categories = data.categories
    if data.min_score is not None:
        profile.min_score = data.min_score
    if data.is_active is not None:
        profile.is_active = data.is_active
    if data.schedule_interval is not None:
        profile.schedule_interval = None if data.schedule_interval == "manual" else data.schedule_interval
        
    session.commit()
    session.refresh(profile)
    return profile


@app.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: int, session: Session = Depends(get_session)):
    profile = session.query(SearchProfile).filter(SearchProfile.id == profile_id).one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    
    session.delete(profile)
    session.commit()
    return {"status": "deleted"}


# --- Управление каналами уведомлений (Notification Channels) ---

@app.get("/api/profiles/{profile_id}/channels", response_model=list[NotificationChannelResponse])
def get_profile_channels(profile_id: int, session: Session = Depends(get_session)):
    return session.query(NotificationChannel).filter(NotificationChannel.profile_id == profile_id).all()


@app.post("/api/profiles/{profile_id}/channels", response_model=NotificationChannelResponse)
def create_or_update_channel(profile_id: int, data: NotificationChannelCreate, session: Session = Depends(get_session)):
    # Проверяем, существует ли профиль
    profile = session.query(SearchProfile).filter(SearchProfile.id == profile_id).one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
        
    channel = session.query(NotificationChannel).filter(
        NotificationChannel.profile_id == profile_id,
        NotificationChannel.type == data.type
    ).first()
    
    if channel:
        channel.name = data.name
        channel.config = data.config
        channel.is_active = data.is_active
    else:
        channel = NotificationChannel(
            profile_id=profile_id,
            type=data.type,
            name=data.name,
            config=data.config,
            is_active=data.is_active,
        )
        session.add(channel)
        
    session.commit()
    session.refresh(channel)
    return channel


# --- Запуск действий (Actions) ---

@app.post("/api/actions/ingest")
def trigger_ingest(background_tasks: BackgroundTasks):
    global task_status
    with status_lock:
        if task_status["ingest"] == "running":
            return {"status": "already_running"}
    background_tasks.add_task(run_ingest_task)
    return {"status": "started"}


@app.post("/api/actions/notify")
def trigger_notify(background_tasks: BackgroundTasks):
    global task_status
    with status_lock:
        if task_status["notify"] == "running":
            return {"status": "already_running"}
    background_tasks.add_task(run_notify_task)
    return {"status": "started"}


# --- Существующие эндпоинты ---

@app.get("/tenders")
def tenders(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    matched_only: bool = False,
    q: str | None = Query(default=None, min_length=1),
    session: Session = Depends(get_session),
):
    items = list_tenders(
        session,
        limit=limit,
        offset=offset,
        matched_only=matched_only,
        query=q,
    )

    return {
        "items": [serialize_tender(item) for item in items],
        "limit": limit,
        "offset": offset,
    }


@app.get("/tenders/{tender_id}")
def tender(tender_id: int, session: Session = Depends(get_session)):
    item = get_tender(session, tender_id)

    if item is None:
        raise HTTPException(status_code=404, detail="Tender not found")

    return serialize_tender(item)


@app.get("/matches")
def matches(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    items = list_matches(session, limit=limit, offset=offset)

    return {
        "items": [serialize_match(item) for item in items],
        "limit": limit,
        "offset": offset,
    }


def run_scheduled_profile_ingest_and_notify(profile_id: int):
    from loguru import logger
    logger.info(f"Starting scheduled ingest and notify for profile ID {profile_id}")
    
    from belzakupki_db.session import SessionLocal
    from worker.ingest import ingest_goszakupki_tenders, ingest_icetrade_tenders, run_ai_analysis_for_new_matches
    from worker.notifications import dispatch_notifications
    
    try:
        with SessionLocal() as session:
            profile = session.query(SearchProfile).filter(SearchProfile.id == profile_id).one_or_none()
            if not profile or not profile.is_active:
                logger.warning(f"Profile ID {profile_id} not active or not found. Skipping scheduled run.")
                return
            
            # 1. Ingest
            logger.info(f"Scheduler: Ingesting tenders for profile '{profile.name}' (ID {profile.id})")
            ingest_goszakupki_tenders(session, profiles=[profile], limit=20)
            ingest_icetrade_tenders(session, profiles=[profile], limit=20)
            session.commit()
            
            # 2. AI Analysis for new matches of this profile
            logger.info(f"Scheduler: Running AI analysis for new matches")
            run_ai_analysis_for_new_matches(session, "goszakupki_by")
            run_ai_analysis_for_new_matches(session, "icetrade_by")
            session.commit()
            
            # 3. Dispatch notifications for new matches
            logger.info(f"Scheduler: Dispatching notifications")
            dispatch_notifications(session)
            session.commit()
            
            logger.info(f"Scheduled run completed successfully for profile ID {profile_id}")
    except Exception as e:
        logger.error(f"Error during scheduled run for profile ID {profile_id}: {e}")


def start_scheduler_loop():
    def scheduler_worker():
        from datetime import datetime, timezone
        from loguru import logger
        import time
        from belzakupki_db.session import SessionLocal
        
        logger.info("Background scheduler thread started.")
        
        while True:
            try:
                with SessionLocal() as session:
                    # Fetch active profiles with scheduler interval set
                    profiles = session.query(SearchProfile).filter(
                        SearchProfile.is_active == True,
                        SearchProfile.schedule_interval.isnot(None),
                        SearchProfile.schedule_interval != "manual"
                    ).all()
                    
                    now = datetime.now(timezone.utc)
                    
                    for profile in profiles:
                        # Determine interval in seconds
                        interval_str = profile.schedule_interval
                        if not interval_str:
                            continue
                            
                        # Parse interval (e.g. "1h", "4h", "12h", "24h")
                        seconds = None
                        try:
                            if interval_str.endswith("h"):
                                seconds = int(interval_str[:-1]) * 3600
                            elif interval_str.endswith("d"):
                                seconds = int(interval_str[:-1]) * 86400
                            elif interval_str.endswith("m"):
                                seconds = int(interval_str[:-1]) * 60
                        except ValueError:
                            logger.error(f"Invalid schedule interval '{interval_str}' for profile {profile.id}")
                            continue
                            
                        if seconds is None:
                            continue
                            
                        should_run = False
                        if profile.last_run_at is None:
                            should_run = True
                        else:
                            last_run = profile.last_run_at
                            if last_run.tzinfo is None:
                                last_run = last_run.replace(tzinfo=timezone.utc)
                            elapsed = (now - last_run).total_seconds()
                            if elapsed >= seconds:
                                should_run = True
                                
                        if should_run:
                            logger.info(f"Scheduler: Profile '{profile.name}' (ID {profile.id}) is due for run. Last run: {profile.last_run_at}")
                            # Update last_run_at BEFORE starting so we don't double-trigger if it takes long
                            profile.last_run_at = now
                            session.add(profile)
                            session.commit()
                            
                            # Run the task in a separate thread so it doesn't block the scheduler loop
                            t = threading.Thread(
                                target=run_scheduled_profile_ingest_and_notify,
                                args=(profile.id,),
                                daemon=True
                            )
                            t.start()
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
                
            time.sleep(60) # Poll every 60 seconds
            
    thread = threading.Thread(target=scheduler_worker, daemon=True)
    thread.start()


@app.on_event("startup")
def on_startup():
    start_scheduler_loop()

