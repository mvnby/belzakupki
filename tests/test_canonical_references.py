from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from belzakupki_db.base import Base
from belzakupki_db.models import TenderSource
from worker.ingest import enrich_tender_if_needed, upsert_tender
from worker.sources.canonical import (
    normalize_procurement_url, preserve_canonical_reference, tender_canonical_url,
)
from worker.sources.icetrade_by import parse_tender_details_html


@pytest.mark.parametrize("url, expected", [
    ("http://WWW.GOSZAKUPKI.BY:80/request/view/3837417/?utm_source=gias#top", "https://goszakupki.by/request/view/3837417"),
    ("https://goszakupki.by/single-source-reference/view/3732488", "https://goszakupki.by/single-source-reference/view/3732488"),
    (" https://www.goszakupki.by/limited/view/3836760/ ", "https://goszakupki.by/limited/view/3836760"),
    ("http://www.icetrade.by/tenders/all/view/4242?from=gias#top", "https://icetrade.by/tenders/all/view/4242"),
    ("http://www.zakupki.butb.by/auctions/viewinvitation.html?utm_source=gias&auction=PR2026001#top", "https://zakupki.butb.by/auctions/viewinvitation.html?auction=PR2026001"),
])
def test_normalizes_exact_procurement_reference(url, expected):
    assert normalize_procurement_url(url) == expected


@pytest.mark.parametrize("url", [
    None, {}, "", "https://goszakupki.by", "https://goszakupki.by/get-file/123",
    "https://goszakupki.by/unverified/view/1", "https://goszakupki.by/request/view/0",
    "https://goszakupki.by/request/view/-1", "https://goszakupki.by/request/view/001",
    "https://goszakupki.by/request/view/1/extra", "https://goszakupki.by/request/view/%31",
    "https://goszakupki.by.evil.test/request/view/1", "https://evil.goszakupki.by/request/view/1",
    "https://user:pass@goszakupki.by/request/view/1", "https://goszakupki.by:444/request/view/1",
    "https://goszakupki.by:80/request/view/1", "ftp://goszakupki.by/request/view/1",
    "https://goszakupki.by/request/view/1\n?q=2", "https://goszakupki.by\\@evil.test/request/view/1",
    "\nhttps://goszakupki.by/request/view/1", "https://goszakupki.by/request/view/1\t",
    "https://goszakupki.by/request/view/1\x7f", "https://goszakupki.by/limited/view/3836760//",
    "https://icetrade.by/getFile/12", "https://icetrade.by/tenders/all/view/0",
    "https://zakupki.butb.by/auctions/viewinvitation.html?auction=A&auction=B",
    "https://zakupki.butb.by/auctions/viewinvitation.html?auction=",
    "https://zakupki.butb.by/auctions/viewinvitation.html?auction=A%26B",
])
def test_rejects_unproven_or_unsafe_identity(url):
    assert normalize_procurement_url(url) is None


def test_procedure_kind_id_and_butb_auction_are_identity():
    urls = [
        "https://goszakupki.by/request/view/1", "https://goszakupki.by/single-source/view/1",
        "https://goszakupki.by/request/view/2",
        "https://zakupki.butb.by/auctions/viewinvitation.html?auction=PR1",
        "https://zakupki.butb.by/auctions/viewinvitation.html?auction=PR2",
    ]
    assert len({normalize_procurement_url(url) for url in urls}) == len(urls)


def test_existing_gias_reference_uses_only_current_not_parent_or_documents():
    current = "https://goszakupki.by/single-source-reference/view/3732488"
    parent = "https://goszakupki.by/request/view/3775146"
    raw = {"raw_data": {"auctionUrl": current, "oneSourcePurchase": {"auctionUrl": parent},
                        "links": [{"link": "https://goszakupki.by/get-file/123"}]}}
    assert tender_canonical_url("gias_by", "https://gias.by/gias/#/purchase/current/135259", raw) == current
    assert tender_canonical_url("goszakupki_by", current, {}) == current
    del raw["raw_data"]["auctionUrl"]
    assert tender_canonical_url("gias_by", "https://gias.by/gias/#/purchase/current/135259", raw) is None


def test_canonical_native_url_does_not_cross_source_or_trust_arbitrary_metadata():
    url = "https://goszakupki.by/request/view/1"
    assert tender_canonical_url("icetrade_by", url, {}) is None
    assert tender_canonical_url("goszakupki_by", url, {"canonical_url": "https://goszakupki.by/request/view/2"}) == url


def test_icetrade_only_explicit_current_reference_and_ambiguity_fails_closed():
    original = "https://goszakupki.by/request/view/123"
    related = "https://goszakupki.by/request/view/456"
    irrelevant = f'<table><tr><th>Связанная закупка</th><td><a href="{related}">Ранее</a></td></tr></table>'
    assert "canonical_url" not in parse_tender_details_html(irrelevant)
    row = f'<tr><th>Ссылка на закупку:</th><td><a href="{original}">Оригинал</a></td></tr>'
    assert parse_tender_details_html(f"<table>{row}</table>{irrelevant}")["canonical_url"] == original
    conflicting = row + f'<tr><th>Ссылка на оригинал закупки</th><td><a href="{related}">Другой</a></td></tr>'
    details = parse_tender_details_html(f"<table>{conflicting}</table>")
    assert details["canonical_url"] is None
    assert details["canonical_reference_conflict"] == [original, related]
    malformed = row.replace(original, "https://goszakupki.by/get-file/123")
    assert parse_tender_details_html(f"<table>{malformed}</table>")["canonical_url"] is None


def test_conflicting_new_reference_is_latched_and_missing_reference_preserves():
    old = {"raw_data": {"auctionUrl": "https://goszakupki.by/request/view/1"}}
    refreshed = preserve_canonical_reference("gias_by", {"title": "Listing"}, old)
    assert tender_canonical_url("gias_by", "https://gias.by/", refreshed) == old["raw_data"]["auctionUrl"]
    incoming = {"raw_data": {"auctionUrl": "https://goszakupki.by/request/view/2"}}
    conflict = preserve_canonical_reference("gias_by", incoming, refreshed)
    assert conflict["canonical_reference_conflict"] == [old["raw_data"]["auctionUrl"], incoming["raw_data"]["auctionUrl"]]
    assert tender_canonical_url("gias_by", "https://gias.by/", conflict) is None
    repeated = preserve_canonical_reference("gias_by", incoming, conflict)
    assert tender_canonical_url("gias_by", "https://gias.by/", repeated) is None


def test_real_icetrade_invitation_ignores_homepage_and_document_links():
    html = (Path(__file__).parent / "fixtures" / "icetrade_1407896_reference.html").read_text()
    original = "https://goszakupki.by/limited/view/3836760"
    details = parse_tender_details_html(html)
    assert details["canonical_url"] == original
    assert tender_canonical_url("icetrade_by", "https://icetrade.by/tenders/all/view/1407896", details) == original
    assert tender_canonical_url("goszakupki_by", original, {}) == original
    # Document links may also appear beside the invitation itself.
    html = html.replace("открыть приглашение на площадке</a>",
                        'открыть приглашение на площадке</a><a href="https://goszakupki.by/limited/get-file/101">Файл</a>')
    assert parse_tender_details_html(html)["canonical_url"] == original


@pytest.mark.parametrize("source", ["gias_by", "icetrade_by"])
def test_verified_identity_survives_invalid_reference_before_later_conflict(source):
    def evidence(value):
        return {"raw_data": {"auctionUrl": value}} if source == "gias_by" else {"canonical_url": value}
    original = "https://goszakupki.by/limited/view/3836760"
    other = "https://goszakupki.by/limited/view/3836761"
    saved = preserve_canonical_reference(source, evidence(original))
    invalid = preserve_canonical_reference(source, evidence("https://goszakupki.by/limited/get-file/101"), saved)
    assert tender_canonical_url(source, "https://icetrade.by/tenders/all/view/1407896", invalid) is None
    assert invalid["canonical_reference_verified"] == original
    listing = preserve_canonical_reference(source, {"title": "Refreshed listing"}, invalid)
    assert tender_canonical_url(source, "https://icetrade.by/tenders/all/view/1407896", listing) is None
    conflict = preserve_canonical_reference(source, evidence(other), listing)
    assert conflict["canonical_reference_conflict"] == [original, other]
    assert tender_canonical_url(source, "https://icetrade.by/tenders/all/view/1407896", conflict) is None


@pytest.mark.parametrize("empty", [None, "", "  "])
def test_gias_null_search_fallback_is_missing_detail_not_conflicting_reference(empty):
    old = {"raw_data": {"auctionUrl": "https://goszakupki.by/request/view/1"}}
    refreshed = preserve_canonical_reference("gias_by", {"raw_data": {"auctionUrl": empty}}, old)
    assert tender_canonical_url("gias_by", "https://gias.by/", refreshed) == old["raw_data"]["auctionUrl"]


def test_listing_upsert_then_detail_failure_preserves_verified_original(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    original = "https://goszakupki.by/request/view/123"
    listing = {"external_id": "42", "title": "Procurement", "url": "https://icetrade.by/tenders/all/view/42"}
    with Session(engine) as session:
        source = TenderSource(code="icetrade_by", name="Ice", base_url="https://icetrade.by")
        session.add(source)
        session.flush()
        tender, _ = upsert_tender(session, source, {**listing, "canonical_url": original})
        session.commit()
        tender, created = upsert_tender(session, source, {**listing, "title": "Refreshed"})
        def unavailable(url):
            raise RuntimeError("source unavailable")
        monkeypatch.setattr("worker.sources.icetrade_by.fetch_tender_details", unavailable)
        enrich_tender_if_needed(session, tender, created, 1, "icetrade_by")
        session.commit()
        assert tender_canonical_url(source.code, tender.url, tender.raw_data) == original
        assert tender.url == listing["url"] and tender.external_id == "42"
    engine.dispose()
