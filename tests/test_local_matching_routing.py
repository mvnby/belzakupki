from __future__ import annotations

from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(element, compiler, **kw):
    return "JSON"

from belzakupki_db.base import Base
from belzakupki_db.models import TenderSource, Tender, SearchProfile, TenderMatch
from belzakupki_db.enums import MatchStatus
from worker.routing import run_local_profile_routing
from unittest.mock import patch

@pytest.fixture
def db_session():
    # Используем SQLite в памяти для тестов
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionClass = sessionmaker(bind=engine)
    session = SessionClass()
    try:
        yield session
    finally:
        session.close()

@patch("worker.routing.enrich_tender_if_needed")
def test_run_local_profile_routing(mock_enrich, db_session: Session):
    # 1. Создаем тестовый источник
    source = TenderSource(code="goszakupki_by", name="Goszakupki", base_url="http://example.com")
    db_session.add(source)
    db_session.flush()
    
    # 2. Создаем поисковые профили
    profile_hvac = SearchProfile(
        name="HVAC Profile",
        keywords=["кондиционер", "вентиляция"],
        negative_keywords=["бытовой"],
        min_score=Decimal("5.0"),
        is_active=True,
    )
    profile_inactive = SearchProfile(
        name="Inactive Profile",
        keywords=["кондиционер"],
        min_score=Decimal("5.0"),
        is_active=False,
    )
    db_session.add(profile_hvac)
    db_session.add(profile_inactive)
    db_session.flush()
    
    # 3. Создаем тендеры
    # Тендер A: Должен подойти под активный профиль (keywords совпали), не проверен
    tender_a = Tender(
        source_id=source.id,
        external_id="tender_a",
        title="Поставка кондиционеров и вентиляционного оборудования",
        url="http://example.com/a",
        is_matched_checked=False,
        status="posted"
    )
    # Тендер B: Совпало ключевое слово, но заблокирован негативным словом
    tender_b = Tender(
        source_id=source.id,
        external_id="tender_b",
        title="Поставка бытовых кондиционеров",
        url="http://example.com/b",
        is_matched_checked=False,
        status="posted"
    )
    # Тендер C: Был проверен ранее, должен быть пропущен роутингом
    tender_c = Tender(
        source_id=source.id,
        external_id="tender_c",
        title="Поставка кондиционеров",
        url="http://example.com/c",
        is_matched_checked=True,
        status="posted"
    )
    # Тендер D: Не совпадает по ключевым словам
    tender_d = Tender(
        source_id=source.id,
        external_id="tender_d",
        title="Поставка офисных столов",
        url="http://example.com/d",
        is_matched_checked=False,
        status="posted"
    )
    
    db_session.add_all([tender_a, tender_b, tender_c, tender_d])
    db_session.commit()
    
    # 4. Запускаем роутинг
    matched_count = run_local_profile_routing(db_session)
    
    # 5. Проверяем результаты
    # Должен быть только 1 матч (tender_a подошел под active_hvac)
    assert matched_count == 1
    
    # Проверяем записи TenderMatch в БД
    matches = db_session.query(TenderMatch).all()
    assert len(matches) == 1
    match = matches[0]
    assert match.tender_id == tender_a.id
    assert match.profile_id == profile_hvac.id
    assert match.status == MatchStatus.NEW
    assert "кондиционер" in match.matched_keywords
    
    # Проверяем, что флаг is_matched_checked проставился в True для всех необработанных тендеров
    db_session.refresh(tender_a)
    db_session.refresh(tender_b)
    db_session.refresh(tender_c)
    db_session.refresh(tender_d)
    
    assert tender_a.is_matched_checked is True
    assert tender_b.is_matched_checked is True
    assert tender_c.is_matched_checked is True  # остался True
    assert tender_d.is_matched_checked is True
    
    # Проверяем, что enrich_tender_if_needed вызвался ровно один раз для совпавшего тендера A
    mock_enrich.assert_called_once_with(db_session, tender_a, was_created=True, matches_count=1, source_code="goszakupki_by")
