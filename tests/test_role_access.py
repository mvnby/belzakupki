from __future__ import annotations

import os
os.environ["API_SECRET_KEY"] = "test-secret-key-for-unit-testing"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(element, compiler, **kw):
    return "JSON"

from belzakupki_db.base import Base
from belzakupki_db.models import Tenant, User, TenderSource, Tender
from belzakupki_db.session import get_session
from apps.api.main import app

from sqlalchemy.pool import StaticPool

@pytest.fixture
def client_and_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    
    def override_get_session():
        try:
            yield session
        finally:
            pass
            
    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app)
    
    yield client, session
    
    session.close()
    app.dependency_overrides.clear()
    engine.dispose()


def test_admin_stats_access(client_and_session):
    client, session = client_and_session

    # 1. Create Admin User & Tenant
    admin_tenant = Tenant(name="Admin Org")
    session.add(admin_tenant)
    session.flush()

    # We register via endpoints to encrypt passwords properly
    client.post("/api/auth/register", json={
        "email": "admin@belzakupki.by",
        "password": "adminpassword",
        "full_name": "Admin System",
        "tenant_name": "Admin Org"
    })
    
    # Update role to admin manually in DB
    user_admin = session.query(User).filter(User.email == "admin@belzakupki.by").first()
    user_admin.role = "admin"
    session.add(user_admin)
    session.commit()

    token_admin = client.post("/api/auth/login", json={
        "email": "admin@belzakupki.by",
        "password": "adminpassword"
    }).json()["access_token"]

    # 2. Create Regular Manager User & Tenant
    client.post("/api/auth/register", json={
        "email": "manager@belzakupki.by",
        "password": "managerpassword",
        "full_name": "Manager User",
        "tenant_name": "Manager Org"
    })
    
    # Update manager role to manager in DB (registration defaults to admin)
    user_manager = session.query(User).filter(User.email == "manager@belzakupki.by").first()
    user_manager.role = "manager"
    session.add(user_manager)
    session.commit()

    token_manager = client.post("/api/auth/login", json={
        "email": "manager@belzakupki.by",
        "password": "managerpassword"
    }).json()["access_token"]

    # 3. Verify Admin Access
    admin_resp = client.get("/api/admin/stats", headers={"Authorization": f"Bearer {token_admin}"})
    assert admin_resp.status_code == 200
    assert "user_count" in admin_resp.json()
    assert admin_resp.json()["user_count"] == 2

    # 4. Verify Manager Access (Blocked)
    manager_resp = client.get("/api/admin/stats", headers={"Authorization": f"Bearer {token_manager}"})
    assert manager_resp.status_code == 403
    assert "Доступ запрещен" in manager_resp.json()["detail"]


def test_anonymous_guest_preview_feed(client_and_session):
    client, session = client_and_session

    # Setup a mock source and tenders
    source = TenderSource(code="goszakupki_by", name="Goszakupki", base_url="http://example.com")
    session.add(source)
    session.flush()

    t1 = Tender(
        source_id=source.id,
        external_id="tender_today",
        title="Today's Active HVAC Work",
        url="http://example.com/hvac",
        status="posted",
        raw_data={"lots": [{"name": "Lot 1"}], "attachments": [{"name": "file.pdf"}]}
    )
    session.add(t1)
    session.commit()

    # 1. Anonymous GET /api/tenders (Allowed)
    anonymous_resp = client.get("/api/tenders")
    assert anonymous_resp.status_code == 200
    
    items = anonymous_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Today's Active HVAC Work"
    
    # Verify specifications are stripped for Guests
    assert items[0]["lots"] == []
    assert items[0]["attachments"] == []
    assert items[0]["ai_relevance"] is None

    # 2. Anonymous GET /api/tenders/{id} (Blocked with 401)
    anonymous_detail_resp = client.get(f"/api/tenders/{t1.id}")
    assert anonymous_detail_resp.status_code == 401
