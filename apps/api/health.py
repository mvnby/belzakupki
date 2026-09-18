"""Small health probes; never substitute the SPA for a successful probe."""
import os
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from redis import Redis
from rq import Worker
from sqlalchemy import text
from belzakupki_db.session import SessionLocal

router = APIRouter(tags=["Operations"])


def dependencies_ready() -> Redis:
    with SessionLocal() as session:
        session.execute(text("SELECT 1"))
    redis = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), socket_timeout=3, socket_connect_timeout=3)
    redis.ping()
    return redis


@router.get("/healthz", include_in_schema=False)
@router.get("/api/health")
def health():
    try:
        dependencies_ready()
    except Exception:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return {"status": "ok"}


@router.get("/api/ready")
def ready():
    try:
        redis = dependencies_ready()
        scheduler = bool(redis.exists("belzakupki:scheduler:heartbeat"))
        now = datetime.now(timezone.utc)
        workers = Worker.all(connection=redis)
        worker = any(w.last_heartbeat and (now - (
            w.last_heartbeat.replace(tzinfo=timezone.utc) if w.last_heartbeat.tzinfo is None else w.last_heartbeat
        )).total_seconds() < 600 for w in workers)
        if not scheduler or not worker:
            return JSONResponse({"status": "unavailable", "scheduler": scheduler, "worker": worker}, status_code=503)
    except Exception:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return {"status": "ok", "scheduler": True, "worker": True}
