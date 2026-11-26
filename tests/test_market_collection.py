from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from belzakupki_db.base import Base
from belzakupki_db.models import SearchProfile, Tender, TenderMatch
from worker import ingest
from worker.sources import goszakupki_by, icetrade_by


@pytest.mark.parametrize(
    ("source", "search_class"),
    [(goszakupki_by, goszakupki_by.GoszakupkiSearch), (icetrade_by, icetrade_by.IcetradeSearch)],
)
def test_market_searches_share_the_notice_limit(source, search_class, monkeypatch):
    words = ["кондиционер", "вентиляция", "холодильное оборудование"]
    searches = [search_class(text=word) for word in words]
    seen = []

    def get(url):
        return httpx.Response(200, request=httpx.Request("GET", url), text="<html></html>")

    def parse(_, *, search):
        seen.append(search.text)
        prefix = words.index(search.text) + 1
        return [{"external_id": "common"}, *[{"external_id": f"{prefix}-{index}"} for index in range(25)]]

    client = MagicMock()
    client.get.side_effect = get
    client.__enter__.return_value = client
    if source is goszakupki_by:
        monkeypatch.setattr(goszakupki_by.httpx, "Client", Mock(return_value=client))
    else:
        monkeypatch.setattr(icetrade_by, "_create_client", Mock(return_value=client))
        monkeypatch.setattr(icetrade_by, "_execute_request", lambda _, __, url: get(url))
    monkeypatch.setattr(source, "parse_tenders_html", parse)

    legacy = source.fetch_tenders_for_searches(searches, limit=20)
    assert len(legacy) == 20 and seen == [words[0]]
    seen.clear()
    market = source.fetch_tenders_for_searches([*searches, searches[0]], limit=20, balanced=True)
    identities = [row["external_id"] for row in market]
    assert seen == words
    assert len(identities) == len(set(identities)) == 20
    assert identities[:4] == ["common", "1-0", "2-0", "3-0"]


def test_market_collection_uses_native_lot_evidence_and_reuses_an_unchanged_inventory(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    listing = {
        "external_id": "555",
        "title": "Ремонт помещений",
        "url": "https://goszakupki.by/request/view/555",
        "status": "posted",
        "deadline_at": datetime.now(timezone.utc) + timedelta(days=1),
    }
    lots = [{"number": "1", "name": "Монтаж кондиционера", "delivery_place": "г. Лепель"}]
    source = Mock(return_value=[listing])
    hydrate = Mock(return_value={"lots": lots, "lot_inventory_complete": True, "attachments": []})
    paid = Mock()
    monkeypatch.setattr(goszakupki_by, "fetch_dynamic_tenders", source)
    monkeypatch.setattr(goszakupki_by, "fetch_tender_details", hydrate)
    monkeypatch.setattr(ingest, "run_ai_analysis_for_new_matches", paid)

    with Session(engine) as session:
        crm = SearchProfile(name="CRM", keywords=["ремонт"], is_active=True)
        market = SearchProfile(name="Рынок", keywords=["кондиционер"], is_active=True)
        session.add_all([crm, market])
        session.commit()
        for _ in range(2):
            result = ingest.ingest_goszakupki_tenders(session, profiles=[market], market_only=True, limit=20)
            assert result.matches == 1
        assert session.scalar(select(Tender)).raw_data["lots"] == lots
        matches = session.scalars(select(TenderMatch)).all()
        assert [row.profile_id for row in matches] == [market.id]
        assert matches[0].ai_relevance is None
    engine.dispose()
    assert all(call.kwargs["balanced"] for call in source.call_args_list)
    hydrate.assert_called_once_with(listing["url"])
    paid.assert_not_called()
