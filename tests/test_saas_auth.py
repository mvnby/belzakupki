from __future__ import annotations

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
from belzakupki_db.models import Tenant, User, SearchProfile, TenderMatch, NotificationChannel, NotificationLog
from belzakupki_db.session import get_session
from apps.api.main import app

from sqlalchemy.pool import StaticPool

@pytest.fixture
def client():
    # Use SQLite in-memory database with StaticPool to share a single connection across all API calls
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
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


def test_saas_register_and_login(client):
    # 1. Register user & tenant
    response = client.post("/api/auth/register", json={
        "email": "test@belzakupki.by",
        "password": "testpassword",
        "full_name": "Test User",
        "tenant_name": "Test Company Ltd"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@belzakupki.by"
    assert data["full_name"] == "Test User"
    assert data["role"] == "manager"
    assert data["tenant_id"] is not None

    # 2. Login
    response = client.post("/api/auth/login", json={
        "email": "test@belzakupki.by",
        "password": "testpassword"
    })
    assert response.status_code == 200
    token_data = response.json()
    assert token_data["token_type"] == "bearer"
    assert "access_token" in token_data
    token = token_data["access_token"]

    # 3. Get /me
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    me_data = response.json()
    assert me_data["email"] == "test@belzakupki.by"
    assert me_data["full_name"] == "Test User"


def test_tenant_isolation(client):
    # Create Tenant A & User A
    client.post("/api/auth/register", json={
        "email": "usera@tenant.by",
        "password": "passworda",
        "full_name": "User A",
        "tenant_name": "Tenant A"
    })
    token_a = client.post("/api/auth/login", json={
        "email": "usera@tenant.by",
        "password": "passworda"
    }).json()["access_token"]

    # Create Tenant B & User B
    client.post("/api/auth/register", json={
        "email": "userb@tenant.by",
        "password": "passwordb",
        "full_name": "User B",
        "tenant_name": "Tenant B"
    })
    token_b = client.post("/api/auth/login", json={
        "email": "userb@tenant.by",
        "password": "passwordb"
    }).json()["access_token"]

    # User A creates a SearchProfile
    profile_response = client.post("/api/profiles", json={
        "name": "Profile A",
        "keywords": ["hvac"],
        "min_score": 10.0
    }, headers={"Authorization": f"Bearer {token_a}"})
    assert profile_response.status_code == 200
    profile_a_id = profile_response.json()["id"]

    # User B lists profiles - should NOT see User A's profile
    list_b = client.get("/api/profiles", headers={"Authorization": f"Bearer {token_b}"})
    assert list_b.status_code == 200
    profiles_b = list_b.json()
    assert len(profiles_b) == 0

    # User A lists profiles - should see "Profile A"
    list_a = client.get("/api/profiles", headers={"Authorization": f"Bearer {token_a}"})
    assert list_a.status_code == 200
    profiles_a = list_a.json()
    assert len(profiles_a) == 1
    assert profiles_a[0]["name"] == "Profile A"

    # User B tries to update Profile A - should fail with 404 (access denied)
    update_response = client.put(f"/api/profiles/{profile_a_id}", json={
        "name": "Hacked Profile"
    }, headers={"Authorization": f"Bearer {token_b}"})
    assert update_response.status_code == 404
