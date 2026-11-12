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
from worker.ingest import extract_tender_region, score_tender
from unittest.mock import patch


@pytest.mark.parametrize("raw_data, expected", [
    ({"search_regions": ["2"]}, "2"),
    ({"region": "1", "search_regions": ["2"]}, "1"),
    ({"search_regions": []}, None),
    ({"search_regions": ["1", "2"]}, None),
    ({"search_regions": ["2", "2"]}, None),
    ({"search_regions": ["99"]}, None),
    ({"search_regions": [2]}, None),
    ({"search_regions": [{}]}, None),
    ({"search_regions": "2"}, None),
    ({}, None),
])
def test_region_requires_unambiguous_canonical_search_context(raw_data, expected):
    tender = Tender(title="Обслуживание кондиционеров", raw_data=raw_data)
    assert extract_tender_region(tender) == expected


def test_ambiguous_search_context_preserves_text_region_fallback():
    tender = Tender(
        title="Обслуживание кондиционеров",
        customer_name="Витебская областная больница",
        raw_data={"search_regions": ["1", "2"]},
    )
    assert extract_tender_region(tender) == "2"

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


@pytest.mark.parametrize("customer,title", [
    ("Дубровенский районный исполнительный комитет", "Ремонт вентиляции"),
    ("Толочинская центральная районная больница", "Обслуживание кондиционеров"),
    ("Браславская центральная районная больница", "Ремонт кондиционера"),
    ("Лиозненская центральная районная больница", "Обслуживание кондиционеров"),
])
def test_regional_search_matches_hvac_outside_regional_capital(db_session, customer, title):
    source = TenderSource(code="goszakupki_by", name="Goszakupki", base_url="https://example.com")
    profile = SearchProfile(
        name="Vitebsk HVAC", keywords=["кондиционер", "вентиляция"],
        negative_keywords=["автомобильные"], regions=["2"],
        min_score=Decimal("20"), is_active=True,
    )
    db_session.add_all([source, profile])
    db_session.flush()
    tender = Tender(
        source_id=source.id, external_id="regional-hvac", title=title,
        customer_name=customer, url="https://example.com/tender",
        raw_data={"search_regions": ["2"]},
    )
    db_session.add(tender)
    db_session.flush()

    assert score_tender(db_session, tender) == 1
    db_session.flush()
    match = db_session.query(TenderMatch).one()
    assert match.profile_id == profile.id
    assert match.score >= profile.min_score

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


@patch("worker.routing.enrich_tender_if_needed")
def test_local_profile_routing_with_regions(mock_enrich, db_session: Session):
    # 1. Создаем источник
    source = TenderSource(code="goszakupki_by", name="Goszakupki", base_url="http://example.com")
    db_session.add(source)
    db_session.flush()
    
    # 2. Создаем поисковые профили с региональными ограничениями
    profile_vitebsk = SearchProfile(
        name="Vitebsk HVAC",
        keywords=["кондиционер"],
        regions=["2"], # Витебская область
        min_score=Decimal("5.0"),
        is_active=True,
    )
    profile_all = SearchProfile(
        name="All Belarus HVAC",
        keywords=["кондиционер"],
        regions=[], # Все регионы
        min_score=Decimal("5.0"),
        is_active=True,
    )
    db_session.add(profile_vitebsk)
    db_session.add(profile_all)
    db_session.flush()
    
    # 3. Создаем тендеры с разными регионами
    # Т1: Витебск (должен подойти под оба профиля)
    tender_vitebsk = Tender(
        source_id=source.id,
        external_id="tender_vitebsk",
        title="Закупка кондиционера",
        customer_name="УЗ Витебская областная клиническая больница",
        url="http://example.com/v",
        is_matched_checked=False,
        status="posted"
    )
    # Т2: Брест (должен подойти только под profile_all)
    tender_brest = Tender(
        source_id=source.id,
        external_id="tender_brest",
        title="Закупка кондиционера",
        customer_name="Брестский облисполком",
        url="http://example.com/b",
        is_matched_checked=False,
        status="posted"
    )
    
    db_session.add_all([tender_vitebsk, tender_brest])
    db_session.commit()
    
    # 4. Запускаем роутинг
    matched_count = run_local_profile_routing(db_session)
    
    # 5. Проверяем результаты
    # Т1 (vitebsk) подошел под 2 профиля (Vitebsk HVAC, All Belarus HVAC)
    # Т2 (brest) подошел под 1 профиль (All Belarus HVAC)
    # Итого должно быть 3 совпадения (matches)
    assert matched_count == 3
    
    # Проверяем записи в БД
    matches_vitebsk = db_session.query(TenderMatch).filter(TenderMatch.tender_id == tender_vitebsk.id).all()
    assert len(matches_vitebsk) == 2
    
    matches_brest = db_session.query(TenderMatch).filter(TenderMatch.tender_id == tender_brest.id).all()
    assert len(matches_brest) == 1
    assert matches_brest[0].profile_id == profile_all.id

