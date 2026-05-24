from __future__ import annotations

from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

# Map JSONB to JSON for SQLite dialect during testing
@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(element, compiler, **kw):
    return "JSON"

from belzakupki_db.base import Base
from belzakupki_db.models import TenderSource, Tender, SearchProfile, TenderMatch, TenderResult
from belzakupki_db.enums import MatchStatus
from apps.api.main import extract_numeric_value


@pytest.fixture
def db_session():
    # Use SQLite in-memory database for testing
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionClass = sessionmaker(bind=engine)
    session = SessionClass()
    try:
        yield session
    finally:
        session.close()


def test_extract_numeric_value():
    assert extract_numeric_value("37 700 BYN") == 37700.0
    assert extract_numeric_value("12 345,67 USD") == 12345.67
    assert extract_numeric_value("123.45") == 123.45
    assert extract_numeric_value(None) is None
    assert extract_numeric_value("abc") is None
    assert extract_numeric_value("10,000.50") == 10000.50


def test_update_match_status(db_session: Session):
    # Setup test data
    source = TenderSource(code="gk", name="Goszakupki", base_url="http://example.com")
    db_session.add(source)
    db_session.flush()
    
    tender = Tender(
        source_id=source.id,
        external_id="123",
        title="Test Tender",
        url="http://example.com/123",
        status="posted"
    )
    db_session.add(tender)
    
    profile = SearchProfile(
        name="Test Profile",
        keywords=["test"],
        min_score=Decimal("10.0")
    )
    db_session.add(profile)
    db_session.flush()
    
    match = TenderMatch(
        tender_id=tender.id,
        profile_id=profile.id,
        score=Decimal("20.0"),
        status=MatchStatus.NEW
    )
    db_session.add(match)
    db_session.commit()
    
    # Test update status logic
    assert match.status == MatchStatus.NEW
    match.status = MatchStatus.IN_WORK
    db_session.commit()
    
    # Reload and assert
    db_session.refresh(match)
    assert match.status == MatchStatus.IN_WORK


def test_analytics_calculations(db_session: Session):
    # Setup test data for competitor and customer analytics
    source = TenderSource(code="gk", name="Goszakupki", base_url="http://example.com")
    db_session.add(source)
    db_session.flush()
    
    # Tender 1: Winner A, Customer X
    t1 = Tender(
        source_id=source.id,
        title="Tender 1",
        customer_name="Customer X",
        url="http://example.com/1",
        raw_data={"estimated_value": "100 000 BYN"}
    )
    db_session.add(t1)
    
    # Tender 2: Winner A, Customer Y
    t2 = Tender(
        source_id=source.id,
        title="Tender 2",
        customer_name="Customer Y",
        url="http://example.com/2",
        raw_data={"estimated_value": "200 000 BYN"}
    )
    db_session.add(t2)
    
    # Tender 3: Winner B, Customer X
    t3 = Tender(
        source_id=source.id,
        title="Tender 3",
        customer_name="Customer X",
        url="http://example.com/3",
        raw_data={"estimated_value": "150 000 BYN"}
    )
    db_session.add(t3)
    db_session.flush()
    
    # Bidding results
    r1 = TenderResult(
        tender_id=t1.id,
        status="Состоялась",
        winner_name="Winner A",
        winner_unp="111111",
        contract_price=Decimal("80000.00")
    )
    db_session.add(r1)
    
    r2 = TenderResult(
        tender_id=t2.id,
        status="Состоялась",
        winner_name="Winner A",
        winner_unp="111111",
        contract_price=Decimal("170000.00")
    )
    db_session.add(r2)
    
    r3 = TenderResult(
        tender_id=t3.id,
        status="Состоялась",
        winner_name="Winner B",
        winner_unp="222222",
        contract_price=Decimal("135000.00")
    )
    db_session.add(r3)
    db_session.commit()
    
    # Let's perform aggregation queries like get_competitor_analytics does
    # 1. Top Winners
    from sqlalchemy import select, func
    winner_stmt = (
        select(
            TenderResult.winner_name,
            TenderResult.winner_unp,
            func.count(TenderResult.id).label("wins_count"),
            func.sum(TenderResult.contract_price).label("total_amount")
        )
        .where(TenderResult.winner_name != None)
        .group_by(TenderResult.winner_name, TenderResult.winner_unp)
        .order_by(func.count(TenderResult.id).desc())
    )
    winners = db_session.execute(winner_stmt).all()
    assert len(winners) == 2
    assert winners[0].winner_name == "Winner A"
    assert winners[0].wins_count == 2
    assert float(winners[0].total_amount) == 250000.0
    
    # 2. Price Reduction
    stmt = (
        select(TenderResult.contract_price, Tender.raw_data)
        .join(Tender, Tender.id == TenderResult.tender_id)
        .where(TenderResult.contract_price != None)
    )
    results = db_session.execute(stmt).all()
    
    percentages = []
    for contract_price, raw_data in results:
        est_str = raw_data.get("estimated_value")
        est_val = extract_numeric_value(est_str)
        con_val = float(contract_price)
        if est_val and est_val > 0:
            percentages.append((est_val - con_val) / est_val * 100)
            
    avg_discount = sum(percentages) / len(percentages) if percentages else 0.0
    # Expected percentages:
    # t1: (100k - 80k)/100k = 20%
    # t2: (200k - 170k)/200k = 15%
    # t3: (150k - 135k)/150k = 10%
    # Average: (20 + 15 + 10) / 3 = 15%
    assert round(avg_discount, 2) == 15.0
