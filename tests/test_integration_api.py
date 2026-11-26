from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import app
from apps.api.auth import validate_security_config
from belzakupki_db.base import Base
from belzakupki_db.models import Tenant, User, SearchProfile, TenderSource, Tender, TenderDocument, TenderMatch
from belzakupki_db.session import get_session
from worker.sources.goszakupki_by import parse_tender_details_html


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


def test_feed_exports_existing_gias_reference_without_changing_native_access(integration):
    client, session, matches, headers = integration
    tender = matches[0].tender
    tender.source.code = "gias_by"
    tender.source.base_url = "https://gias.by"
    tender.url = "https://gias.by/gias/#/purchase/current/135259"
    tender.external_id = "135259"
    original = "https://goszakupki.by/single-source-reference/view/3732488"
    tender.raw_data = {"raw_data": {
        "auctionUrl": original,
        "oneSourcePurchase": {"auctionUrl": "https://goszakupki.by/request/view/3775146"},
    }}
    session.commit()
    exported = client.get("/api/v1/opportunities", headers=headers).json()["items"][0]["tender"]
    assert exported["canonical_url"] == original
    assert exported["source"] == "gias_by"
    assert exported["external_id"] == "135259"
    assert exported["url"] == tender.url
    detail = client.get("/api/v1/tenders/gias_by/135259", headers=headers)
    assert detail.status_code == 200 and detail.json()["source_url"] == tender.url
    other = matches[1].tender
    assert client.get(f"/api/v1/tenders/gias_by/{other.external_id}", headers=headers).status_code == 404


def test_tender_detail_and_document_download_are_tenant_scoped(integration, monkeypatch):
    client, session, matches, headers = integration
    tender = matches[0].tender
    tender.customer_name = "ООО Заказчик"
    tender.raw_data = {
        "source_number": "BZ-455",
        "estimated_value": "12000 BYN",
        "currency": "BYN",
        "contacts": {"name": "Иванов И.И.", "phone": "+375291234567", "email": "mail@example.org"},
        "unp": "123456789",
        "legal_address": "г. Минск, ул. Тестовая, 1",
        "lots": [{"number": "1", "name": "Оборудование", "quantity": "8 шт."}],
        "attachments": [
            {"name": "specification.doc", "url": "https://example.org/files/specification.doc"},
            {"name": "unsafe.doc", "url": "http://example.org/files/unsafe.doc"},
            {"name": "other-host.doc", "url": "https://untrusted.example/files/other-host.doc"},
        ],
    }
    session.add(TenderDocument(tender_id=tender.id, file_name="specification.doc", content="equipment details"))
    session.commit()

    detail = client.get("/api/v1/tenders/test_source/0", headers=headers)
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["source"] == "test_source"
    assert payload["external_id"] == "0"
    assert payload["customer"] == {
        "name": "ООО Заказчик", "unp": "123456789",
        "legal_address": "г. Минск, ул. Тестовая, 1", "postal_address": None,
        "contacts": {"name": "Иванов И.И.", "phone": "+375291234567", "email": "mail@example.org"},
    }
    assert payload["objects"] == [{"number": "1", "name": "Оборудование", "quantity": "8 шт."}]
    assert len(payload["documents"]) == 1
    document = payload["documents"][0]
    assert document["name"] == "specification.doc"
    assert document["source_url"] == "https://example.org/files/specification.doc"
    assert document["extracted_text"] == "equipment details"
    assert document["extracted_text_truncated"] is False

    monkeypatch.setattr("apps.api.opportunities._download_document", lambda source, url, base_url: iter([b"original bytes"]))
    downloaded = client.get(
        f"/api/v1/tenders/test_source/0/documents/{document['id']}", headers=headers,
    )
    assert downloaded.status_code == 200
    assert downloaded.content == b"original bytes"
    assert downloaded.headers["content-disposition"] == 'attachment; filename="specification.doc"'

    monkeypatch.setenv("INTEGRATION_PROFILE_IDS", "2")
    assert client.get("/api/v1/tenders/test_source/0", headers=headers).status_code == 404
    monkeypatch.delenv("INTEGRATION_PROFILE_IDS")
    monkeypatch.setenv("INTEGRATION_TENANT_ID", "2")
    assert client.get("/api/v1/tenders/test_source/0", headers=headers).status_code == 404


def _goszakupki_tender(integration):
    _, session, matches, _ = integration
    tender = matches[0].tender
    tender.source.code = "goszakupki_by"
    tender.source.base_url = "https://goszakupki.by"
    tender.external_id = "3783338"
    tender.url = "https://goszakupki.by/request/view/3783338"
    tender.raw_data = {"attachments": []}
    session.commit()
    return tender


def test_recovers_archive_from_scoped_publication_without_reloading_saved_text(integration, monkeypatch):
    from apps.api import goszakupki_document_inventory as inventory

    client, session, _, headers = integration
    tender = _goszakupki_tender(integration)
    attachment = {"name": "Проект и смета.zip", "url": "https://goszakupki.by/get-file/estimate.zip?download=1"}
    fetch = Mock(return_value=f'<a href="{attachment["url"]}">{attachment["name"]}</a>')
    monkeypatch.setattr(inventory, "_cache", OrderedDict())
    monkeypatch.setattr(inventory, "fetch_tender_html", fetch)
    session.add(TenderDocument(tender_id=tender.id, file_name=attachment["name"], content="text from an earlier version"))
    session.commit()
    url = "/api/v1/tenders/goszakupki_by/3783338"

    assert client.get(url).status_code == 401
    fetch.assert_not_called()
    card = client.get(url, headers=headers).json()
    assert card["document_inventory_complete"]
    (file,) = card["documents"]
    assert file["name"] == attachment["name"] and file["extracted_text"] is None

    download = Mock(return_value=iter([b"archive bytes"]))
    monkeypatch.setattr("apps.api.opportunities._download_document", download)
    response = client.get(f"{url}/documents/{file['id']}", headers=headers)
    assert response.status_code == 200 and response.content == b"archive bytes"
    assert response.headers["content-disposition"].startswith("attachment; filename*=UTF-8''")
    fetch.assert_called_once_with(tender.url, timeout=3, max_page_bytes=2 * 1024 * 1024)
    download.assert_called_once_with("goszakupki_by", attachment["url"], tender.source.base_url)
    session.refresh(tender)
    assert tender.raw_data["attachments"] == []

    monkeypatch.setenv("INTEGRATION_TENANT_ID", "2")
    assert client.get(f"{url}/documents/{file['id']}", headers=headers).status_code == 404
    assert download.call_count == 1


def test_inventory_failure_is_temporarily_cached_and_then_retried(integration, monkeypatch):
    from apps.api import goszakupki_document_inventory as inventory

    client, _, _, headers = integration
    _goszakupki_tender(integration)
    fetch = Mock(side_effect=[
        httpx.ConnectError("upstream unavailable"),
        '<a href="/get-file/specification.pdf">ТЗ.pdf</a>',
    ])
    monkeypatch.setattr(inventory, "_cache", OrderedDict())
    monkeypatch.setattr(inventory, "fetch_tender_html", fetch)
    clock = Mock(return_value=1.0)
    monkeypatch.setattr(inventory, "monotonic", clock)
    url = "/api/v1/tenders/goszakupki_by/3783338"
    for _ in range(2):
        card = client.get(url, headers=headers).json()
        assert not card["documents"] and not card["document_inventory_complete"]
    assert fetch.call_count == 1

    clock.return_value = 22.0
    card = client.get(url, headers=headers).json()
    assert card["document_inventory_complete"] and len(card["documents"]) == 1
    assert fetch.call_count == 2


def test_detail_recovers_misparsed_lots_and_attachments_in_the_same_lookup(integration, monkeypatch):
    from apps.api import goszakupki_document_inventory as inventory

    client, session, _, headers = integration
    tender = _goszakupki_tender(integration)
    tender.raw_data = {"lots": [
        {"number": "Техническое обслуживание кондиционеров", "quantity": "Подача предложений"},
        {"number": "Лот ", "quantity": "Место поставки: г. Витебск"},
    ]}
    session.commit()
    fetch = Mock(return_value="""
        <a href="/get-file/specification.pdf">specification.pdf</a>
        <table id="lotsList"><tbody><tr class="lot-row">
          <th class="lot-num">1</th><td class="lot-description">Техническое обслуживание кондиционеров</td>
          <td class="lot-count-price">9 единиц, 1 368.00 BYN</td><td class="lot-status">Подача предложений</td>
        </tr><tr class="lot-inf" id="lot-inf-1"><td>
          <b>Место поставки товара:</b><span class="col-md-6">г. Витебск</span>
        </td></tr></tbody></table>
    """)
    monkeypatch.setattr(inventory, "_cache", OrderedDict())
    monkeypatch.setattr(inventory, "fetch_tender_html", fetch)
    card = client.get("/api/v1/tenders/goszakupki_by/3783338", headers=headers).json()
    assert card["document_inventory_complete"] and len(card["documents"]) == 1
    assert card["lot_inventory_complete"]
    assert len(card["lots"]) == 1 and card["lots"][0]["delivery_place"] == "г. Витебск"
    fetch.assert_called_once_with(tender.url, timeout=3, max_page_bytes=2 * 1024 * 1024)
    session.refresh(tender)
    assert tender.raw_data["lots"][1]["number"] == "Лот "


def test_opportunity_feed_uses_saved_public_lot_fields_without_live_requests(integration, monkeypatch):
    from apps.api import goszakupki_document_inventory as inventory

    client, session, matches, headers = integration
    tender = _goszakupki_tender(integration)
    tender.raw_data = {
        "lot_inventory_complete": True,
        "lots": [{"number": "1", "name": "Монтаж кондиционера", "delivery_place": "г. Лепель",
                  "status": "Подача предложений", "unrelated_raw_field": "do not export"}],
    }
    session.commit()
    source_read = Mock(side_effect=AssertionError("Feed must use saved data"))
    monkeypatch.setattr(inventory, "fetch_tender_html", source_read)
    payload = client.get("/api/v1/opportunities", headers=headers).json()
    item = next(item for item in payload["items"] if item["id"] == matches[0].id)
    assert item["tender"]["lot_inventory_complete"]
    (lot,) = item["tender"]["lots"]
    assert lot["number"] == "1" and lot["delivery_place"] == "г. Лепель"
    assert "unrelated_raw_field" not in lot
    source_read.assert_not_called()


def test_market_uses_its_own_profiles_cursor_and_original_scope(integration, monkeypatch):
    from worker.ingest import get_pending_ai_analysis_max_id, run_ai_analysis_for_new_matches

    client, session, matches, headers = integration
    source = _goszakupki_tender(integration).source
    tenant_id = matches[0].profile.tenant_id
    profile = SearchProfile(tenant_id=tenant_id, name="Общий рынок HVAC", keywords=["HVAC"])
    another_profile = SearchProfile(tenant_id=tenant_id, name="Другая рыночная выборка", keywords=["HVAC"])
    session.add_all([profile, another_profile])
    session.flush()
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=40)
    for index, status in enumerate(("open", "Отменен", "open"), 1):
        tender = Tender(
            source_id=source.id, external_id=str(4000 + index), title=f"Общая закупка {index}",
            url=f"https://goszakupki.by/request/view/{4000 + index}", customer_name="Организация",
            status=status, created_at=old if index == 3 else now, updated_at=old if index == 3 else now,
            raw_data={
                "contacts": {"email": "private@example.test"},
                "lot_inventory_complete": True,
                "lots": [{"number": "1", "name": "Монтаж вентиляции", "delivery_place": "г. Витебск"}],
                "attachments": [{"name": "ТЗ.pdf", "url": "https://goszakupki.by/get-file/specification.pdf"}],
            },
        )
        session.add(tender)
        session.flush()
        session.add(TenderMatch(tender_id=tender.id, profile_id=profile.id, score=15,
                                ai_analysis={"reason": "tenant-only analysis"}))
    session.commit()
    operations = "/api/v1/tender-market/publications"
    monkeypatch.setenv("INTEGRATION_PROFILE_IDS", str(matches[0].profile_id))
    monkeypatch.delenv("INTEGRATION_MARKET_PROFILE_IDS", raising=False)
    assert client.get(operations).status_code == 401
    assert client.get(operations, headers=headers).status_code == 503
    monkeypatch.setenv("INTEGRATION_MARKET_PROFILE_IDS", str(profile.id))
    assert get_pending_ai_analysis_max_id(session, source.code) is None
    assert run_ai_analysis_for_new_matches(session, source.code).selected_count == 0

    response = client.get(operations, params={"limit": 1}, headers=headers)
    assert response.status_code == 200, response.text
    page = response.json()
    (first,) = page["items"]
    assert first["external_id"] == "4001" and first["active"]
    assert first["lot_inventory_complete"] and first["lots"][0]["delivery_place"] == "г. Витебск"
    assert "customer_name" not in first and "contacts" not in first and "ai_analysis" not in first
    next_page = client.get(operations, params={"cursor": page["next_cursor"]}, headers=headers).json()
    assert next_page["items"][0]["external_id"] == "4002" and not next_page["items"][0]["active"]
    assert not next_page["has_more"]
    assert client.get("/api/v1/opportunities", params={"cursor": page["next_cursor"]}, headers=headers).status_code == 400
    crm = client.get("/api/v1/opportunities", headers=headers).json()
    assert all(item["tender"]["external_id"] != "4001" for item in crm["items"])

    detail_url = "/api/v1/tender-market/tenders/goszakupki_by/4001"
    response = client.get(detail_url, headers=headers)
    assert response.status_code == 200 and response.json()["customer"]["contacts"] is None
    document = response.json()["documents"][0]
    monkeypatch.setattr("apps.api.opportunities._download_document", lambda *args: iter([b"original"]))
    assert client.get(f"{detail_url}/documents/{document['id']}", headers=headers).content == b"original"
    assert client.get("/api/v1/tenders/goszakupki_by/4001", headers=headers).status_code == 404
    assert client.get("/api/v1/tender-market/tenders/goszakupki_by/3783338", headers=headers).status_code == 404
    monkeypatch.setenv("INTEGRATION_MARKET_PROFILE_IDS", str(another_profile.id))
    assert client.get(operations, params={"cursor": page["next_cursor"]}, headers=headers).status_code == 400
    monkeypatch.setenv("INTEGRATION_MARKET_PROFILE_IDS", str(matches[0].profile_id))
    assert client.get(operations, headers=headers).status_code == 503
    monkeypatch.setenv("INTEGRATION_MARKET_PROFILE_IDS", "123456789")
    assert client.get(operations, headers=headers).status_code == 503


def test_goszakupki_source_customer_fields_reach_scoped_api(integration):
    from pathlib import Path

    client, session, matches, headers = integration
    html = Path(__file__).parent.joinpath(
        "fixtures/goszakupki_customer_details.html"
    ).read_text(encoding="utf-8")
    tender = matches[0].tender
    tender.customer_name = "Организация-заказчик"
    tender.raw_data = parse_tender_details_html(html)
    session.commit()

    response = client.get("/api/v1/tenders/test_source/0", headers=headers)
    assert response.status_code == 200, response.text
    customer = response.json()["customer"]
    assert customer == {
        "name": "Организация-заказчик",
        "unp": "300050210",
        "legal_address": "г. Минск, ул. Примерная, 12",
        "postal_address": None,
        "contacts": {
            "name": "Иванов Иван Иванович",
            "phone": "+375 29 123-45-67",
            "email": "customer@example.by",
        },
    }


def test_document_download_validates_each_redirect(monkeypatch):
    from apps.api import opportunities

    class Response:
        def __init__(self, status_code, headers=None, chunks=()):
            self.status_code = status_code
            self.headers = headers or {}
            self._chunks = chunks

        @property
        def is_redirect(self):
            return 300 <= self.status_code < 400

        def raise_for_status(self):
            if self.status_code >= 400:
                raise HTTPException(self.status_code, "upstream error")

        def iter_bytes(self, chunk_size):
            yield from self._chunks

    class Stream:
        def __init__(self, response):
            self.response = response

        def __enter__(self):
            return self.response

        def __exit__(self, *args):
            return False

    class Client:
        responses = []
        requested_urls = []

        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            return Response(200)

        def stream(self, method, url):
            self.requested_urls.append(url)
            return Stream(self.responses.pop(0))

    monkeypatch.setattr(opportunities.httpx, "Client", Client)
    monkeypatch.setattr(opportunities, "_provider_download_settings", lambda source: ({}, True, None))

    Client.responses = [
        Response(302, {"location": "/files/final.doc"}),
        Response(200, {"content-length": "2"}, [b"ok"]),
    ]
    assert list(opportunities._download_document(
        "test_source", "https://example.org/files/start.doc", "https://example.org",
    )) == [b"ok"]
    assert Client.requested_urls == [
        "https://example.org/files/start.doc", "https://example.org/files/final.doc",
    ]

    Client.requested_urls = []
    Client.responses = [Response(302, {"location": "https://127.0.0.1/private"})]
    with pytest.raises(HTTPException, match="redirect is unavailable"):
        list(opportunities._download_document(
            "test_source", "https://example.org/files/start.doc", "https://example.org",
        ))
    assert Client.requested_urls == ["https://example.org/files/start.doc"]

    assert opportunities._safe_source_url("https://example.org:444/doc", "https://example.org") is None
    assert opportunities._safe_source_url("https://user:pass@example.org/doc", "https://example.org") is None
    assert opportunities._safe_source_url("https://example.org/doc", "https://user:pass@example.org") is None
    assert opportunities._safe_source_url(
        "https://cdn.example.org:8443/doc", "https://example.org:8443",
    ) == "https://cdn.example.org:8443/doc"


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
