from __future__ import annotations
import pytest
from unittest.mock import patch, AsyncMock
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(element, compiler, **kw):
    return "JSON"

from belzakupki_db.base import Base
from belzakupki_db.models import Tenant, User, SearchProfile, TenderMatch, Tender, TenderSource, CrmConfig
from belzakupki_db.session import get_session
from apps.api.main import app
from sqlalchemy.pool import StaticPool

TestingSessionLocal = None

@pytest.fixture
def client():
    global TestingSessionLocal
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


def test_crm_config_endpoints(client):
    # 1. Register & login
    client.post("/api/auth/register", json={
        "email": "crm@belzakupki.by",
        "password": "crmpassword",
        "full_name": "CRM Manager",
        "tenant_name": "CRM Enterprise"
    })
    token = client.post("/api/auth/login", json={
        "email": "crm@belzakupki.by",
        "password": "crmpassword"
    }).json()["access_token"]
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # 2. GET initially empty
    resp = client.get("/api/crm/settings", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 0
    
    # 3. POST bitrix24 settings
    resp = client.post("/api/crm/settings", json={
        "crm_type": "bitrix24",
        "is_active": True,
        "webhook_url": "https://company.bitrix24.ru/rest/1/abcde/"
    }, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["crm_type"] == "bitrix24"
    assert data["is_active"] is True
    assert data["webhook_url"] == "https://company.bitrix24.ru/rest/1/abcde/"
    
    # 4. POST amoCRM settings
    resp = client.post("/api/crm/settings", json={
        "crm_type": "amocrm",
        "is_active": True,
        "subdomain": "company",
        "api_token": "my-secret-token"
    }, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["crm_type"] == "amocrm"
    assert data["is_active"] is True
    assert data["subdomain"] == "company"
    assert data["api_token"] == "********"  # masked
    
    # 5. GET configs - bitrix24 should now be INACTIVE because amocrm is active
    resp = client.get("/api/crm/settings", headers=headers)
    configs = resp.json()
    assert len(configs) == 2
    
    bitrix = next(c for c in configs if c["crm_type"] == "bitrix24")
    amocrm = next(c for c in configs if c["crm_type"] == "amocrm")
    assert bitrix["is_active"] is False
    assert amocrm["is_active"] is True
    
    # 6. Test updating without replacing token
    resp = client.post("/api/crm/settings", json={
        "crm_type": "amocrm",
        "is_active": True,
        "subdomain": "new-company",
        "api_token": "********"  # should keep my-secret-token in DB
    }, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["subdomain"] == "new-company"


@patch("apps.api.services.crm_service.export_to_bitrix24", new_callable=AsyncMock)
@patch("apps.api.services.crm_service.export_to_amocrm", new_callable=AsyncMock)
def test_export_match_to_crm(mock_export_amo, mock_export_bitrix, client):
    mock_export_bitrix.return_value = "deal_12345"
    mock_export_amo.return_value = "lead_67890"

    # Register & Login
    client.post("/api/auth/register", json={
        "email": "export@belzakupki.by",
        "password": "exportpassword",
        "full_name": "Export Manager",
        "tenant_name": "Export Corp"
    })
    token = client.post("/api/auth/login", json={
        "email": "export@belzakupki.by",
        "password": "exportpassword"
    }).json()["access_token"]
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # Configure Bitrix24 active
    client.post("/api/crm/settings", json={
        "crm_type": "bitrix24",
        "is_active": True,
        "webhook_url": "https://company.bitrix24.ru/rest/1/abcde/"
    }, headers=headers)

    # Let's seed database with SearchProfile, TenderSource, Tender, and TenderMatch
    session = TestingSessionLocal()
    tenant = session.query(Tenant).first()
    
    source = TenderSource(code="test_src", name="Test Source", base_url="https://test.by")
    session.add(source)
    session.flush()
    
    profile = SearchProfile(
        tenant_id=tenant.id,
        name="Metal structures",
        keywords=["metal"],
        min_score=10.0
    )
    session.add(profile)
    session.flush()
    
    tender = Tender(
        source_id=source.id,
        title="Закупка металлоконструкций на завод",
        customer_name="ОАО Завод",
        url="https://test.by/tender/1",
        raw_data={"estimated_value": "150 000 BYN"}
    )
    session.add(tender)
    session.flush()
    
    match = TenderMatch(
        tender_id=tender.id,
        profile_id=profile.id,
        score=90.0,
        matched_keywords=["metal"],
        status="new"
    )
    session.add(match)
    session.commit()
    match_id = match.id
    session.close()

    # Trigger export
    resp = client.post(f"/api/tenders/matches/{match_id}/export-crm", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["crm_deal_id"] == "deal_12345"
    assert data["status"] == "in_work"
    
    # Check mock call arguments
    mock_export_bitrix.assert_called_once()
    args, kwargs = mock_export_bitrix.call_args
    assert args[0] == "https://company.bitrix24.ru/rest/1/abcde/"
    assert args[1].title == "Закупка металлоконструкций на завод"
    assert args[2].score == 90.0
