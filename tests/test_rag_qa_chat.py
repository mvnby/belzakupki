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
from belzakupki_db.models import Tenant, User, SearchProfile, TenderMatch, Tender, TenderSource, TenderDocument, TenderChatHistory
from belzakupki_db.session import get_session
from apps.api.main import app, retrieve_relevant_context
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


def test_context_retrieval_trimming():
    # Test paragraph retrieval when context exceeds max length
    paragraphs = [
        "Абзац 1: Это текст про поставку кондиционеров марки Daikin.",
        "Абзац 2: Условия оплаты предусматривают отсрочку платежа 60 дней.",
        "Абзац 3: Штрафные санкции составляют 0.1% от цены договора за каждый день просрочки.",
        "Абзац 4: Поставка осуществляется в город Минск."
    ]
    full_text = "\n\n".join(paragraphs)
    
    # query matches Daikin and Минск
    query = "Где Daikin и Минск?"
    trimmed = retrieve_relevant_context(full_text, query, max_chars=120)
    
    # Trimmed should prioritize paragraphs with query terms
    assert "Daikin" in trimmed
    assert "Минск" in trimmed
    assert len(trimmed) <= 120


def test_match_qa_chat(client):
    # 1. Register & Login
    client.post("/api/auth/register", json={
        "email": "chat_user@belzakupki.by",
        "password": "chatpassword",
        "full_name": "Chat User",
        "tenant_name": "Chat Enterprise"
    })
    token = client.post("/api/auth/login", json={
        "email": "chat_user@belzakupki.by",
        "password": "chatpassword"
    }).json()["access_token"]
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # 2. Seed DB with Tender, TenderMatch, and TenderDocuments
    session = TestingSessionLocal()
    tenant = session.query(Tenant).first()
    tenant.plan = "professional"
    session.add(tenant)
    session.flush()
    user = session.query(User).first()
    
    source = TenderSource(code="test_src", name="Test Source", base_url="https://test.by")
    session.add(source)
    session.flush()
    
    profile = SearchProfile(
        tenant_id=tenant.id,
        name="HVAC profile",
        keywords=["hvac"],
        min_score=10.0
    )
    session.add(profile)
    session.flush()
    
    tender = Tender(
        source_id=source.id,
        title="Закупка систем кондиционирования",
        customer_name="ОАО Завод",
        url="https://test.by/tender/1",
        raw_data={}
    )
    session.add(tender)
    session.flush()
    
    match = TenderMatch(
        tender_id=tender.id,
        profile_id=profile.id,
        score=85.0,
        matched_keywords=["hvac"],
        status="new"
    )
    session.add(match)
    session.flush()
    
    # Add document specifications
    doc1 = TenderDocument(
        tender_id=tender.id,
        file_name="spec_1.txt",
        content="Технические требования: вентиляция Daikin и кондиционеры. Сроки поставки: 30 дней."
    )
    doc2 = TenderDocument(
        tender_id=tender.id,
        file_name="contract_draft.txt",
        content="Оплата: отсрочка платежа 10 банковских дней после поставки."
    )
    session.add(doc1)
    session.add(doc2)
    session.commit()
    
    match_id = match.id
    session.close()

    # 3. GET chat history (should be empty initially)
    resp = client.get(f"/api/matches/{match_id}/chat", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 0

    # 4. POST chat message (with simulated AI response fallback since DEEPSEEK_TOKEN is absent)
    resp = client.post(f"/api/matches/{match_id}/chat", json={
        "message": "Каковы сроки оплаты?"
    }, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "assistant"
    assert "Вы спросили" in data["message"]
    
    # 5. GET chat history again - should contain 2 messages now (user message & assistant message)
    resp = client.get(f"/api/matches/{match_id}/chat", headers=headers)
    assert resp.status_code == 200
    history = resp.json()
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["message"] == "Каковы сроки оплаты?"
    assert history[1]["role"] == "assistant"
