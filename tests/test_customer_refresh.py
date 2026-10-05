from copy import deepcopy

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from belzakupki_db.base import Base
from belzakupki_db.models import Tender, TenderDocument, TenderSource
from worker.customer_refresh import (
    CustomerRefreshError,
    TARGET_URLS,
    build_customer_refresh_plan,
    execute_customer_refresh_plan,
)


@pytest.fixture
def refresh_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        good_source = TenderSource(code="goszakupki_by", name="Goszakupki", base_url="https://goszakupki.by")
        other_source = TenderSource(code="other", name="Other", base_url="https://other.example")
        session.add_all([good_source, other_source])
        session.flush()
        tenders = []
        for index, (external_id, url) in enumerate(TARGET_URLS.items()):
            tender = Tender(
                source_id=good_source.id,
                external_id=external_id,
                title=f"Tender {external_id}",
                customer_name=f"Customer {index}",
                url=url,
                raw_data={
                    "unp": "old-unp",
                    "legal_address": "old address",
                    "contacts": {"name": "Old name", "phone": "old phone", "email": "old@example.by", "custom": "keep"},
                    "lots": [{"name": "keep lot"}],
                    "attachments": [{"name": "keep.pdf"}],
                    "ai_analysis": {"relevant": True, "reason": "keep"},
                    "custom_payload": {"keep": [1, 2, 3]},
                },
            )
            session.add(tender)
            tenders.append(tender)
        session.flush()
        session.add(TenderDocument(tender_id=tenders[0].id, file_name="source.pdf", content="preserve document"))
        session.commit()
    yield factory
    engine.dispose()


def live_details(url):
    if url.endswith("3722135"):
        return {
            "unp": "300050210",
            "legal_address": "г. Минск, ул. Примерная, 12",
            "contacts": {"name": "Иванов Иван Иванович", "phone": "+375 29 123-45-67", "email": "customer@example.by"},
            "lots": [{"name": "must not replace stored lot"}],
            "ai_analysis": {"relevant": False},
            "attachments": [],
        }
    return {
        "unp": "300582165",
        "legal_address": "г. Гомель, ул. Советская, 8",
        "contacts": {"name": "Петров П.П.", "phone": "+375 17 765-43-21", "email": "customer2@example.by"},
        "lots": [],
    }


def test_default_plan_is_read_only_and_reports_only_customer_fields(refresh_db):
    with refresh_db() as session:
        before = {t.external_id: deepcopy(t.raw_data) for t in session.scalars(select(Tender))}

    plan = build_customer_refresh_plan(session_factory=refresh_db, fetch_details=live_details)

    assert set(record["external_id"] for record in plan["records"]) == set(TARGET_URLS)
    assert plan["records"][0]["before"].keys() == {"name", "unp", "legal_address", "contacts"}
    assert plan["records"][0]["after"]["unp"] in {"300050210", "300582165"}
    assert "_records" in plan
    with refresh_db() as session:
        after = {t.external_id: t.raw_data for t in session.scalars(select(Tender))}
    assert after == before


def test_execute_requires_reviewed_digest_and_preserves_unrelated_fields(refresh_db):
    plan = build_customer_refresh_plan(session_factory=refresh_db, fetch_details=live_details)
    with pytest.raises(CustomerRefreshError, match="digest"):
        execute_customer_refresh_plan(
            reviewed_digest="0" * 64,
            session_factory=refresh_db,
            fetch_details=live_details,
        )

    applied = execute_customer_refresh_plan(
        reviewed_digest=plan["plan_digest"],
        session_factory=refresh_db,
        fetch_details=live_details,
    )
    assert {record["external_id"] for record in applied["records"]} == set(TARGET_URLS)
    with refresh_db() as session:
        tenders = list(session.scalars(select(Tender)))
        document = session.scalar(select(TenderDocument))
        for tender in tenders:
            raw = tender.raw_data
            assert raw["unp"] in {"300050210", "300582165"}
            assert raw["legal_address"] != "old address"
            assert raw["lots"] == [{"name": "keep lot"}]
            assert raw["attachments"] == [{"name": "keep.pdf"}]
            assert raw["ai_analysis"] == {"relevant": True, "reason": "keep"}
            assert raw["custom_payload"] == {"keep": [1, 2, 3]}
            assert raw["contacts"]["custom"] == "keep"
        assert document.content == "preserve document"


def test_plan_refuses_missing_target_row(refresh_db):
    with refresh_db() as session:
        tender = session.scalar(select(Tender).where(Tender.external_id == "3722307"))
        session.delete(tender)
        session.commit()

    with pytest.raises(CustomerRefreshError, match="exactly 2"):
        build_customer_refresh_plan(session_factory=refresh_db, fetch_details=live_details)


def test_execute_rechecks_locked_rows_after_source_fetch(refresh_db):
    plan = build_customer_refresh_plan(session_factory=refresh_db, fetch_details=live_details)
    changed_during_fetch = False

    def mutating_fetch(url):
        nonlocal changed_during_fetch
        if not changed_during_fetch:
            with refresh_db() as session:
                tender = session.scalar(select(Tender).where(Tender.external_id == "3722135"))
                raw = deepcopy(tender.raw_data)
                raw["ai_analysis"]["reason"] = "changed during network request"
                tender.raw_data = raw
                session.commit()
            changed_during_fetch = True
        return live_details(url)

    with pytest.raises(CustomerRefreshError, match="changed after planning"):
        execute_customer_refresh_plan(
            reviewed_digest=plan["plan_digest"],
            session_factory=refresh_db,
            fetch_details=mutating_fetch,
        )
    with refresh_db() as session:
        tender = session.scalar(select(Tender).where(Tender.external_id == "3722135"))
        assert tender.raw_data["unp"] == "old-unp"
        assert tender.raw_data["ai_analysis"]["reason"] == "changed during network request"


def test_plan_refuses_external_id_in_another_source(refresh_db):
    with refresh_db() as session:
        other = session.scalar(select(TenderSource).where(TenderSource.code == "other"))
        session.add(Tender(
            source_id=other.id,
            external_id="3722135",
            title="Wrong source duplicate",
            url=TARGET_URLS["3722135"],
        ))
        session.commit()

    with pytest.raises(CustomerRefreshError, match="exactly 2"):
        build_customer_refresh_plan(session_factory=refresh_db, fetch_details=live_details)

