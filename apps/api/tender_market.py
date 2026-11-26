"""Public procurement inputs from the dedicated Kitlane market profiles."""

import hashlib
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload

from apps.api.auth import signing_secret
from apps.api.opportunities import (
    NativeTenderLot, TenderDetail, _safe_source_url, _saved_lots_summary, _scoped_tender,
    _tender_detail_response, _tender_document_response, cursor_after, integration_tenant, utc,
)
from belzakupki_db.integration_scope import market_profile_ids
from belzakupki_db.models import SearchProfile, Tender, TenderMatch, TenderSource
from belzakupki_db.session import get_session
from worker.sources.canonical import tender_canonical_url

router = APIRouter(prefix="/api/v1/tender-market", tags=["Tender Market"])
_PUBLIC_SOURCES = {"goszakupki_by", "gias_by", "icetrade_by", "butb_by"}
_OPEN_STATES = {
    "posted", "active", "open", "подача предложений", "подача документов/сведений",
    "подача предложений / документов",
}
_RECENT_CHANGE_WINDOW = timedelta(days=1)
_NO_DEADLINE_WINDOW = timedelta(days=30)


class MarketPublication(BaseModel):
    source: str
    external_id: str
    url: str
    canonical_url: str | None
    title: str
    deadline_at: datetime | None
    published_at: datetime | None
    updated_at: datetime
    active: bool
    lots: list[NativeTenderLot]
    lot_inventory_complete: bool


class MarketPage(BaseModel):
    items: list[MarketPublication]
    next_cursor: str | None
    has_more: bool


def _profile_ids(session: Session, tenant_id: int) -> tuple[int, ...]:
    try:
        values = market_profile_ids()
    except ValueError:
        raise HTTPException(503, "Invalid market profile configuration") from None
    if not values:
        raise HTTPException(503, "Tender market profiles are not configured")
    available = set(session.scalars(select(SearchProfile.id).where(
        SearchProfile.id.in_(values), SearchProfile.tenant_id == tenant_id, SearchProfile.is_active.is_(True),
    )))
    if available != set(values):
        raise HTTPException(503, "Market profiles are unavailable")
    return values


def _audience(profile_ids: tuple[int, ...]) -> str:
    digest = hashlib.sha256(",".join(map(str, profile_ids)).encode()).hexdigest()
    return f"tender-market-v1:{digest}"


@router.get("/publications", response_model=MarketPage, operation_id="list_tender_market_publications")
def publications(
    cursor: str | None = Query(None, max_length=2048),
    limit: int = Query(100, ge=1, le=100),
    tenant_id: int = Depends(integration_tenant),
    session: Session = Depends(get_session),
) -> MarketPage:
    """List public candidates from the configured market profiles, including lifecycle updates."""
    profile_ids = _profile_ids(session, tenant_id)
    audience = _audience(profile_ids)
    after_id = cursor_after(cursor, tenant_id, audience=audience)
    now = datetime.now(timezone.utc)
    open_state = func.lower(func.trim(Tender.status)).in_(_OPEN_STATES)
    fresh = or_(
        Tender.deadline_at > now,
        and_(Tender.deadline_at.is_(None), func.coalesce(Tender.published_at, Tender.created_at) >= now - _NO_DEADLINE_WINDOW),
    )
    active = and_(TenderSource.is_active.is_(True), open_state, fresh).label("market_active")
    rows = list(session.execute(
        select(TenderMatch, active).join(TenderMatch.profile).join(TenderMatch.tender).join(Tender.source)
        .where(SearchProfile.tenant_id == tenant_id, SearchProfile.is_active.is_(True),
               TenderMatch.profile_id.in_(profile_ids),
               TenderSource.code.in_(_PUBLIC_SOURCES), TenderMatch.id > after_id,
               or_(active, Tender.updated_at >= now - _RECENT_CHANGE_WINDOW))
        .options(joinedload(TenderMatch.profile), joinedload(TenderMatch.tender).joinedload(Tender.source))
        .order_by(TenderMatch.id).limit(limit + 1)
    ))
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = []
    for match, is_active in rows:
        tender = match.tender
        url = _safe_source_url(tender.url, tender.source.base_url)
        if not url or not tender.external_id:
            continue
        deadline = utc(tender.deadline_at) if tender.deadline_at else None
        raw = tender.raw_data or {}
        lots, complete = _saved_lots_summary(tender, raw)
        items.append(MarketPublication(
            source=tender.source.code, external_id=tender.external_id, url=url, title=tender.title,
            canonical_url=tender_canonical_url(tender.source.code, url, raw),
            deadline_at=deadline, published_at=utc(tender.published_at) if tender.published_at else None,
            updated_at=utc(tender.updated_at),
            active=bool(is_active),
            lots=lots, lot_inventory_complete=complete,
        ))
    next_cursor = jwt.encode(
        {"aud": audience, "tenant_id": tenant_id, "after_id": rows[-1][0].id},
        signing_secret(), algorithm="HS256",
    ) if has_more else None
    return MarketPage(items=items, has_more=has_more, next_cursor=next_cursor)


def _market_tender(source_code: str, external_id: str, tenant_id: int, session: Session) -> Tender:
    if source_code not in _PUBLIC_SOURCES:
        raise HTTPException(404, "Tender is unavailable in the market scope")
    tender = _scoped_tender(source_code, external_id, tenant_id, session, profile_ids=_profile_ids(session, tenant_id))
    if not _safe_source_url(tender.url, tender.source.base_url):
        raise HTTPException(404, "Tender is unavailable in the market scope")
    return tender


@router.get("/tenders/{source_code}/{external_id}", response_model=TenderDetail, operation_id="get_tender_market_detail")
def detail(
    source_code: str, external_id: str,
    tenant_id: int = Depends(integration_tenant), session: Session = Depends(get_session),
) -> TenderDetail:
    """Read native lot conditions and original links within the market profile scope."""
    return _tender_detail_response(_market_tender(source_code, external_id, tenant_id, session), session,
                                   include_customer=False)


@router.get("/tenders/{source_code}/{external_id}/documents/{document_id}", operation_id="download_tender_market_original")
def original(
    source_code: str, external_id: str, document_id: str,
    tenant_id: int = Depends(integration_tenant), session: Session = Depends(get_session),
) -> StreamingResponse:
    """Read one original referenced by an authorized market publication."""
    return _tender_document_response(_market_tender(source_code, external_id, tenant_id, session), document_id, session)
