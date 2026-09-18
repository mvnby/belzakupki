from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import app
from apps.api.auth import validate_security_config
from belzakupki_db.base import Base
from belzakupki_db.models import Tenant, User, SearchProfile, TenderSource, Tender, TenderMatch
from belzakupki_db.session import get_session


@pytest.fixture
def integration(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tenants = [Tenant(name="HVAC"), Tenant(name="Other")]
    session.add_all(tenants)
    session.flush()
    source = TenderSource(code="test_source", name="Test", base_url="https://example.org")
    session.add(source)
    profiles = [SearchProfile(tenant_id=t.id, name=t.name, keywords=["hvac"]) for t in tenants]
    session.add_all(profiles)
    session.flush()
    matches = []
    for i, profile in enumerate([profiles[0], profiles[1], profiles[0]]):
        tender = Tender(source_id=source.id, title=f"Tender {i}", external_id=str(i), url=f"https://example.org/{i}", deadline_at=datetime.now(timezone.utc) + timedelta(days=1))
        session.add(tender)
        session.flush()
        match = TenderMatch(tender_id=tender.id, profile_id=profile.id, score=85, ai_relevance=True, ai_analysis={"relevant": True}, matched_keywords=["hvac"])
        session.add(match)
        matches.append(match)
    session.commit()
    monkeypatch.setenv("API_SECRET_KEY", "test-api-signing-secret-long-enough-12345")
    monkeypatch.setenv("INTEGRATION_API_KEY", "test-integration-secret-long-enough-12345")
    monkeypatch.setenv("INTEGRATION_TENANT_ID", str(tenants[0].id))
    monkeypatch.delenv("INTEGRATION_PROFILE_IDS", raising=False)
    def override():
        yield session
    app.dependency_overrides[get_session] = override
    yield TestClient(app), session, matches, {"Authorization": "Bearer test-integration-secret-long-enough-12345"}
    app.dependency_overrides.clear()
    session.close()
    engine.dispose()


def test_auth_fails_closed_without_secret_and_does_not_seed(integration, monkeypatch):
    client, session, _, _ = integration
    monkeypatch.delenv("API_SECRET_KEY")
    with pytest.raises(RuntimeError, match="API_SECRET_KEY"):
        validate_security_config()
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/admin/stats").status_code == 401
    assert session.scalar(select(func.count(User.id))) == 0


def test_feed_auth_scoping_and_cursor(integration, monkeypatch):
    client, _, matches, headers = integration
    assert client.get("/api/v1/opportunities").status_code == 401
    assert client.get("/api/v1/opportunities", headers={"Authorization": "Bearer wrong"}).status_code == 401
    page = client.get("/api/v1/opportunities?limit=1", headers=headers).json()
    assert [item["id"] for item in page["items"]] == [matches[0].id]
    assert page["has_more"]
    second = client.get("/api/v1/opportunities", params={"cursor": page["next_cursor"]}, headers=headers).json()
    assert [item["id"] for item in second["items"]] == [matches[2].id]
    assert second["next_cursor"] is None and not second["has_more"]
    monkeypatch.setenv("INTEGRATION_TENANT_ID", "2")
    assert client.get("/api/v1/opportunities", params={"cursor": page["next_cursor"]}, headers=headers).status_code == 400
    assert client.get("/api/v1/opportunities", params={"cursor": "bad"}, headers=headers).status_code == 400
    assert client.get("/api/v1/opportunities?limit=101", headers=headers).status_code == 422


def test_reconciliation_catches_old_tender_updates_and_exposes_bypass(integration):
    client, session, matches, headers = integration
    initial = client.get("/api/v1/opportunities", headers=headers).json()
    assert initial["items"][0]["relevance_status"] == "confirmed"
    matches[0].ai_analysis = {"bypassed": True, "relevant": True}
    matches[0].tender.title = "Changed after first scan"
    matches[2].tender.deadline_at = datetime.now(timezone.utc) - timedelta(days=1)
    session.commit()
    refreshed = client.get("/api/v1/opportunities", headers=headers).json()["items"]
    assert refreshed[0]["relevance_status"] == "rules_only"
    assert refreshed[0]["tender"]["title"] == "Changed after first scan"
    assert refreshed[1]["eligible"] is False
    matches[0].ai_relevance = False
    session.commit()
    assert client.get("/api/v1/opportunities", headers=headers).json()["items"][0]["relevance_status"] == "rejected"


def test_profile_allowlist_and_inactive_tenant(integration, monkeypatch):
    client, session, _, headers = integration
    monkeypatch.setenv("INTEGRATION_PROFILE_IDS", "2")
    assert client.get("/api/v1/opportunities", headers=headers).json()["items"] == []
    monkeypatch.setenv("INTEGRATION_PROFILE_IDS", "not-an-id")
    assert client.get("/api/v1/opportunities", headers=headers).status_code == 503
    tenant = session.get(Tenant, 1)
    tenant.is_active = False
    session.commit()
    assert client.get("/api/v1/opportunities", headers=headers).status_code == 403


def test_health_is_json_and_readiness_detects_stopped_worker(monkeypatch):
    import apps.api.health as health
    class Redis:
        def exists(self, key):
            return True
    monkeypatch.setattr(health, "dependencies_ready", lambda: Redis())
    monkeypatch.setattr(health.Worker, "all", lambda **kwargs: [])
    client = TestClient(app)
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/api/ready").status_code == 503
    def failed():
        raise ConnectionError()
    monkeypatch.setattr(health, "dependencies_ready", failed)
    assert client.get("/api/health").status_code == 503


def test_notifications_can_be_disabled_without_touching_database(monkeypatch):
    from worker.notifications import _dispatch_notification_batch
    monkeypatch.setenv("WORKER_NOTIFICATIONS_ENABLED", "false")
    assert _dispatch_notification_batch(None) == (0, 0)
