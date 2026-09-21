from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from belzakupki_db.base import Base
from belzakupki_db.models import Tender, TenderResult, TenderSource
from worker import ingest


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_result_failure_rolls_back_only_its_tender_and_keeps_full_winner_name(
    db_session,
    monkeypatch,
) -> None:
    source = TenderSource(code="gk", name="Goszakupki", base_url="https://goszakupki.by")
    db_session.add(source)
    db_session.flush()
    deadline = datetime.now(timezone.utc) - timedelta(days=1)
    failed_tender = Tender(
        source_id=source.id,
        external_id="failed",
        title="Failed protocol",
        url="https://goszakupki.by/failed",
        deadline_at=deadline,
    )
    successful_tender = Tender(
        source_id=source.id,
        external_id="successful",
        title="Successful protocol",
        url="https://goszakupki.by/successful",
        deadline_at=deadline,
    )
    db_session.add_all([failed_tender, successful_tender])
    db_session.commit()

    full_winner_name = "Победитель " + "длинное наименование " * 40
    result_by_url = {
        failed_tender.url: {"winner_name": "Broken", "unserializable": {"value"}},
        successful_tender.url: {"winner_name": full_winner_name, "status": "Состоялась"},
    }
    monkeypatch.setattr(
        "worker.sources.goszakupki_by.fetch_tender_result",
        lambda url: result_by_url[url],
    )

    batch = ingest.check_results_for_active_tenders(db_session)

    assert batch.selected_count == 2
    assert db_session.scalar(
        select(TenderResult).where(TenderResult.tender_id == failed_tender.id)
    ) is None
    assert db_session.get(Tender, failed_tender.id).status == "posted"
    saved_result = db_session.scalar(
        select(TenderResult).where(TenderResult.tender_id == successful_tender.id)
    )
    assert saved_result is not None
    assert saved_result.winner_name == full_winner_name
    assert saved_result.raw_result_data["winner_name"] == full_winner_name
