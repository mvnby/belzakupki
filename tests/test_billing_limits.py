from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
from unittest.mock import patch, MagicMock

@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(element, compiler, **kw):
    return "JSON"

from belzakupki_db.base import Base
from belzakupki_db.models import Tenant, User, SearchProfile, TenderMatch, NotificationChannel, TenderSource, Tender
from belzakupki_db.session import get_session
from belzakupki_db.enums import MatchStatus
from belzakupki_db.billing import PLAN_LIMITS, check_and_reset_billing_cycle, can_use_ai_credits, increment_ai_credits
from apps.api.main import app

from sqlalchemy.pool import StaticPool

@pytest.fixture
def client_and_session():
    # Setup single SQLite in-memory engine and static pool to allow session sharing between tests and API client
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
            pass  # Keep session open during test
            
    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app)
    
    yield client, session
    
    session.close()
    app.dependency_overrides.clear()
    engine.dispose()


def test_profile_and_channel_api_limits(client_and_session):
    client, session = client_and_session

    # 1. Register a tenant (automatically starts with 'free' plan)
    register_response = client.post("/api/auth/register", json={
        "email": "billing@belzakupki.by",
        "password": "testpassword",
        "full_name": "Billing User",
        "tenant_name": "Billing Tenant"
    })
    assert register_response.status_code == 200
    token = client.post("/api/auth/login", json={
        "email": "billing@belzakupki.by",
        "password": "testpassword"
    }).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Fetch status endpoint
    status_resp = client.get("/api/billing/status", headers=headers)
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["plan"] == "free"
    assert status_data["max_active_profiles"] == 1
    assert status_data["max_channels_per_profile"] == 1
    assert status_data["active_profiles_count"] == 0

    # 2. Create first active profile (allowed)
    p1_resp = client.post("/api/profiles", json={
        "name": "Profile 1",
        "keywords": ["hvac"],
        "min_score": 10.0,
        "is_active": True
    }, headers=headers)
    assert p1_resp.status_code == 200
    profile_1_id = p1_resp.json()["id"]

    # Try to create second active profile (blocked on 'free' plan)
    p2_resp = client.post("/api/profiles", json={
        "name": "Profile 2",
        "keywords": ["ventilation"],
        "min_score": 5.0,
        "is_active": True
    }, headers=headers)
    assert p2_resp.status_code == 403
    assert "Превышен лимит активных профилей" in p2_resp.json()["detail"]

    # Create second profile as INACTIVE (allowed)
    p2_resp = client.post("/api/profiles", json={
        "name": "Profile 2",
        "keywords": ["ventilation"],
        "min_score": 5.0,
        "is_active": False
    }, headers=headers)
    assert p2_resp.status_code == 200
    profile_2_id = p2_resp.json()["id"]

    # Try to update second profile to ACTIVE (blocked)
    p2_update_resp = client.put(f"/api/profiles/{profile_2_id}", json={
        "is_active": True
    }, headers=headers)
    assert p2_update_resp.status_code == 403

    # 3. Channel limit verification
    # Create first channel (allowed)
    ch1_resp = client.post(f"/api/profiles/{profile_1_id}/channels", json={
        "name": "Telegram Channel 1",
        "type": "telegram",
        "config": {"chat_id": "12345"},
        "is_active": True
    }, headers=headers)
    assert ch1_resp.status_code == 200

    # Try to create second active channel (blocked on 'free' plan)
    ch2_resp = client.post(f"/api/profiles/{profile_1_id}/channels", json={
        "name": "Email Channel 2",
        "type": "email",
        "config": {"email_address": "test@example.com"},
        "is_active": True
    }, headers=headers)
    assert ch2_resp.status_code == 403
    assert "Превышен лимит активных каналов" in ch2_resp.json()["detail"]

    # 4. Upgrade Tenant plan to 'starter' in DB to test expanded limits
    tenant = session.query(Tenant).filter(Tenant.name == "Billing Tenant").first()
    assert tenant is not None
    tenant.plan = "starter"
    session.add(tenant)
    session.commit()

    # Verify updated status
    status_resp = client.get("/api/billing/status", headers=headers)
    assert status_resp.json()["plan"] == "starter"
    assert status_resp.json()["max_active_profiles"] == 2

    # Now activating the second profile should succeed (since limit is 2)
    p2_update_resp = client.put(f"/api/profiles/{profile_2_id}", json={
        "is_active": True
    }, headers=headers)
    assert p2_update_resp.status_code == 200


def test_billing_cycle_resets(client_and_session):
    _, session = client_and_session

    tenant = Tenant(
        name="Reset Tenant",
        plan="starter",
        ai_credits_used=15,
        billing_cycle_started_at=datetime.now(timezone.utc) - timedelta(days=31)
    )
    session.add(tenant)
    session.commit()

    # Run reset helper
    check_and_reset_billing_cycle(session, tenant)
    session.commit()

    assert tenant.ai_credits_used == 0
    assert (datetime.now(timezone.utc) - tenant.billing_cycle_started_at.replace(tzinfo=timezone.utc)).total_seconds() < 5


def test_worker_ai_credit_exhaustion_bypass(client_and_session):
    _, session = client_and_session

    # 1. Setup Source, Tenant, Profile, and Tender
    source = TenderSource(code="goszakupki_by", name="Goszakupki", base_url="http://example.com")
    session.add(source)
    session.flush()

    tenant = Tenant(
        name="AI Tenant",
        plan="free",
        ai_credits_used=10,  # Max limit for free is 10
        billing_cycle_started_at=datetime.now(timezone.utc)
    )
    session.add(tenant)
    session.flush()

    profile = SearchProfile(
        tenant_id=tenant.id,
        name="HVAC Test",
        keywords=["кондиционер"],
        min_score=Decimal("10.0"),
        is_active=True
    )
    session.add(profile)
    session.flush()

    tender = Tender(
        source_id=source.id,
        external_id="tender_ai_1",
        title="Поставка кондиционера для офиса",
        url="http://example.com/ai_1",
        is_matched_checked=True,
        status="posted"
    )
    session.add(tender)
    session.flush()

    match = TenderMatch(
        tender_id=tender.id,
        profile_id=profile.id,
        score=Decimal("15.0"),
        matched_keywords=["кондиционер"],
        status="new"
    )
    session.add(match)
    session.commit()

    # 2. Run worker AI analysis and verify bypass
    from worker.ingest import run_ai_analysis_for_new_matches

    # Setup token in environment for worker to consider running AI
    with patch.dict("os.environ", {"DEEPSEEK_TOKEN": "valid-token"}):
        run_ai_analysis_for_new_matches(session, "goszakupki_by")
        session.commit()

    # Check match was bypassed and is marked relevant=True (so it is not blocked)
    updated_match = session.get(TenderMatch, match.id)
    assert updated_match.ai_relevance is True
    assert updated_match.ai_analysis["bypassed"] is True
    assert updated_match.ai_analysis["limit_exceeded"] is True
    assert tenant.ai_credits_used == 10  # Remain unchanged


def test_worker_ai_credit_increment_on_success(client_and_session):
    _, session = client_and_session

    source = TenderSource(code="goszakupki_by", name="Goszakupki", base_url="http://example.com")
    session.add(source)
    session.flush()

    tenant = Tenant(
        name="AI Tenant Success",
        plan="starter",
        ai_credits_used=2,
        billing_cycle_started_at=datetime.now(timezone.utc)
    )
    session.add(tenant)
    session.flush()

    profile = SearchProfile(
        tenant_id=tenant.id,
        name="HVAC Test",
        keywords=["кондиционер"],
        min_score=Decimal("10.0"),
        is_active=True
    )
    session.add(profile)
    session.flush()

    tender = Tender(
        source_id=source.id,
        external_id="tender_ai_2",
        title="Поставка кондиционера для офиса",
        url="http://example.com/ai_2",
        is_matched_checked=True,
        status="posted"
    )
    session.add(tender)
    session.flush()

    match = TenderMatch(
        tender_id=tender.id,
        profile_id=profile.id,
        score=Decimal("15.0"),
        matched_keywords=["кондиционер"],
        status="new"
    )
    session.add(match)
    session.commit()

    # Mock DeepSeek API response for Stage 1 relevance analysis
    mock_stage_1 = MagicMock(return_value={"relevant": False, "explanation": "Not relevant HVAC"})

    from worker.ingest import run_ai_analysis_for_new_matches

    with patch.dict("os.environ", {"DEEPSEEK_TOKEN": "valid-token"}):
        with patch("worker.analyzer.deepseek_client.analyze_relevance_by_metadata", mock_stage_1):
            run_ai_analysis_for_new_matches(session, "goszakupki_by")
            session.commit()

    # Check credits incremented to 3, and match rejected
    updated_match = session.get(TenderMatch, match.id)
    assert updated_match.ai_relevance is False
    assert updated_match.status == MatchStatus.REJECTED_BY_AI
    assert tenant.ai_credits_used == 3
