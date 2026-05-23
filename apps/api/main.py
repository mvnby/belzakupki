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
            # Импортируем с дефолтным пресетом
            ingest_goszakupki_tenders(session, search_preset="hvac-vitebsk", limit=20)
            ingest_icetrade_tenders(session, search_preset="hvac-vitebsk", limit=20)
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
        is_active=data.is_active,
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
    if data.is_active is not None:
        profile.is_active = data.is_active
        
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

