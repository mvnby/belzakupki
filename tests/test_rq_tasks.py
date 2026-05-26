from __future__ import annotations

from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from belzakupki_db.base import Base
from belzakupki_db.models import Tenant, User
from belzakupki_db.session import get_session
from apps.api.main import app

@pytest.fixture
def test_client():
    # Use SQLite in-memory database with StaticPool
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    # Pre-seed default user/tenant so get_current_user fallback works
    session = TestingSessionLocal()
    tenant = Tenant(name="ООО Ромашка")
    session.add(tenant)
    session.flush()
    user = User(
        tenant_id=tenant.id,
        email="admin@belzakupki.by",
        hashed_password="hashed_placeholder",
        full_name="Администратор",
        role="admin"
    )
    session.add(user)
    session.commit()
    session.close()
    
    def override_get_session():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()
            
    app.dependency_overrides[get_session] = override_get_session
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def test_trigger_ingest_rq(test_client):
    """Verifies that trigger_ingest enqueues the job via RQ and sets status in Redis."""
    with patch("apps.api.main.get_redis_client") as mock_redis_client, \
         patch("apps.api.main.Queue") as mock_queue_class:
         
        mock_redis = MagicMock()
        mock_redis.get.return_value = None  # status is idle
        mock_redis_client.return_value = mock_redis
        
        mock_queue = MagicMock()
        mock_queue_class.return_value = mock_queue
        
        response = test_client.post("/api/actions/ingest")
        
        assert response.status_code == 200
        assert response.json() == {"status": "started"}
        
        # Verify status is set and task enqueued
        mock_redis.set.assert_called_once_with("belzakupki:task:ingest:1", "running")
        mock_queue.enqueue.assert_called_once_with("worker.tasks.run_ingest_task_job", 1)


def test_trigger_notify_rq(test_client):
    """Verifies that trigger_notify enqueues the notification job via RQ."""
    with patch("apps.api.main.get_redis_client") as mock_redis_client, \
         patch("apps.api.main.Queue") as mock_queue_class:
         
        mock_redis = MagicMock()
        mock_redis.get.return_value = None  # status is idle
        mock_redis_client.return_value = mock_redis
        
        mock_queue = MagicMock()
        mock_queue_class.return_value = mock_queue
        
        response = test_client.post("/api/actions/notify")
        
        assert response.status_code == 200
        assert response.json() == {"status": "started"}
        
        # Verify status is set and task enqueued
        mock_redis.set.assert_called_once_with("belzakupki:task:notify:1", "running")
        mock_queue.enqueue.assert_called_once_with("worker.tasks.run_notify_task_job", 1)


def test_stats_reads_redis_status(test_client):
    """Verifies that /api/stats endpoint reads task status from Redis."""
    with patch("apps.api.main.get_redis_client") as mock_redis_client:
        mock_redis = MagicMock()
        
        def mock_get(key):
            if "ingest" in key:
                return b"running"
            return b"idle"
            
        mock_redis.get.side_effect = mock_get
        mock_redis_client.return_value = mock_redis
        
        response = test_client.get("/api/stats")
        
        assert response.status_code == 200
        data = response.json()
        assert data["tasks"]["ingest"] == "running"
        assert data["tasks"]["notify"] == "idle"
