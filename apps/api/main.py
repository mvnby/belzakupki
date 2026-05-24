from fastapi import Depends, FastAPI, HTTPException, Query, BackgroundTasks, Response, Security
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.security import APIKeyHeader
from contextlib import asynccontextmanager
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
from belzakupki_db.enums import MatchStatus, NotificationStatus
from apps.api.schemas import (
    SearchProfileCreate,
    SearchProfileUpdate,
    SearchProfileResponse,
    NotificationChannelCreate,
    NotificationChannelResponse,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle — API is stateless: no background threads here.

    The scheduler lives in the worker process (worker/scheduler.py).
    """
    yield
    # Nothing to start or stop in the API process


app = FastAPI(title="belzakupki", lifespan=lifespan)

# --- Аутентификация ---

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: str | None = Security(_api_key_header)) -> None:
    """Проверяет X-API-Key заголовок.

    Если API_SECRET_KEY не задан в окружении — проверка отключена (dev-режим).
    Если задан — все /api/* маршруты требуют корректный ключ.
    """
    secret = os.getenv("API_SECRET_KEY")
    if not secret:
        return  # dev-режим: auth отключена
    if key != secret:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")

# Состояние фоновых задач
task_status = {
    "ingest": "idle",
    "notify": "idle",
}
status_lock = threading.Lock()


def run_ingest_task():
    """Фоновая задача сбора тендеров (Dev-режим).

    Считывает активные профили и запускает сбор с госзакупок и icetrade.
    В промышленной среде планировщик запускается как отдельный демон-поток в воркере.
    """
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
    """Фоновая задача рассылки уведомлений (Dev-режим).

    Инициирует отправку уведомлений по всем новым совпадениям.
    """
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
    """Раздает главную страницу панели управления (HTML)."""
    file_path = "apps/api/static/index.html"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Frontend HTML file not found")
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/style.css")
def read_style():
    file_path = "apps/api/static/style.css"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="style.css not found")
    return FileResponse(file_path, media_type="text/css")


@app.get("/app.js")
def read_app_js():
    file_path = "apps/api/static/app.js"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="app.js not found")
    return FileResponse(file_path, media_type="application/javascript")


# --- Статистика ---

@app.get("/api/stats", dependencies=[Depends(require_api_key)])
def get_stats(session: Session = Depends(get_session)):
    """Возвращает агрегированную статистику по тендерам, совпадениям и уведомлениям, а также статус фоновых задач."""
    total_tenders = session.query(func.count(Tender.id)).scalar() or 0
    total_matches = session.query(func.count(TenderMatch.id)).scalar() or 0
    
    new_matches = session.query(func.count(TenderMatch.id)).filter(TenderMatch.status == MatchStatus.NEW).scalar() or 0
    processed_matches = session.query(func.count(TenderMatch.id)).filter(TenderMatch.status == MatchStatus.PROCESSED).scalar() or 0
    expired_matches = session.query(func.count(TenderMatch.id)).filter(TenderMatch.status == MatchStatus.EXPIRED).scalar() or 0

    sent_logs = session.query(func.count(NotificationLog.id)).filter(NotificationLog.status == NotificationStatus.SENT).scalar() or 0
    error_logs = session.query(func.count(NotificationLog.id)).filter(NotificationLog.status == NotificationStatus.ERROR).scalar() or 0

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

@app.get("/api/profiles", response_model=list[SearchProfileResponse], dependencies=[Depends(require_api_key)])
def get_profiles(
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    """Возвращает список всех поисковых профилей."""
    return (
        session.query(SearchProfile)
        .order_by(SearchProfile.id.asc())
        .limit(limit)
        .offset(offset)
        .all()
    )


@app.post("/api/profiles", response_model=SearchProfileResponse, dependencies=[Depends(require_api_key)])
def create_profile(data: SearchProfileCreate, session: Session = Depends(get_session)):
    """Создает новый поисковый профиль."""
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


@app.put("/api/profiles/{profile_id}", response_model=SearchProfileResponse, dependencies=[Depends(require_api_key)])
def update_profile(profile_id: int, data: SearchProfileUpdate, session: Session = Depends(get_session)):
    """Обновляет параметры существующего поискового профиля."""
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


@app.delete("/api/profiles/{profile_id}", dependencies=[Depends(require_api_key)])
def delete_profile(profile_id: int, session: Session = Depends(get_session)):
    """Удаляет поисковый профиль по его ID."""
    profile = session.query(SearchProfile).filter(SearchProfile.id == profile_id).one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    
    session.delete(profile)
    session.commit()
    return {"status": "deleted"}


# --- Управление каналами уведомлений (Notification Channels) ---

@app.get("/api/profiles/{profile_id}/channels", response_model=list[NotificationChannelResponse], dependencies=[Depends(require_api_key)])
def get_profile_channels(profile_id: int, session: Session = Depends(get_session)):
    """Возвращает все настроенные каналы уведомлений для указанного поискового профиля."""
    return session.query(NotificationChannel).filter(NotificationChannel.profile_id == profile_id).all()


@app.post("/api/profiles/{profile_id}/channels", response_model=NotificationChannelResponse, dependencies=[Depends(require_api_key)])
def create_or_update_channel(profile_id: int, data: NotificationChannelCreate, session: Session = Depends(get_session)):
    """Создает новый или обновляет существующий канал уведомлений для указанного профиля."""
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

@app.post("/api/actions/ingest", dependencies=[Depends(require_api_key)])
def trigger_ingest(background_tasks: BackgroundTasks):
    """Инициирует асинхронный запуск фоновой задачи сбора новых тендеров."""
    global task_status
    with status_lock:
        if task_status["ingest"] == "running":
            return {"status": "already_running"}
    background_tasks.add_task(run_ingest_task)
    return {"status": "started"}


@app.post("/api/actions/notify", dependencies=[Depends(require_api_key)])
def trigger_notify(background_tasks: BackgroundTasks):
    """Инициирует асинхронный запуск фоновой задачи отправки уведомлений."""
    global task_status
    with status_lock:
        if task_status["notify"] == "running":
            return {"status": "already_running"}
    background_tasks.add_task(run_notify_task)
    return {"status": "started"}


# --- Существующие эндпоинты ---

@app.get("/api/tenders", dependencies=[Depends(require_api_key)])
def tenders(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    matched_only: bool = False,
    q: str | None = Query(default=None, min_length=1),
    session: Session = Depends(get_session),
):
    """Возвращает список сохраненных тендеров с поддержкой фильтрации и текстового поиска."""
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


@app.get("/api/tenders/{tender_id}", dependencies=[Depends(require_api_key)])
def tender(tender_id: int, session: Session = Depends(get_session)):
    """Возвращает детальную информацию о конкретном тендере по его ID."""
    item = get_tender(session, tender_id)

    if item is None:
        raise HTTPException(status_code=404, detail="Tender not found")

    return serialize_tender(item)


@app.get("/api/matches", dependencies=[Depends(require_api_key)])
def matches(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    """Возвращает список совпадений тендеров с профилями поиска, отсортированный по уровню соответствия."""
    items = list_matches(session, limit=limit, offset=offset)

    return {
        "items": [serialize_match(item) for item in items],
        "limit": limit,
        "offset": offset,
    }


