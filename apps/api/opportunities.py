"""Versioned, tenant-scoped current-state feed for independent consumers."""
import hashlib
import hmac
import os
from datetime import datetime, timezone
from typing import Any, Literal

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from apps.api.auth import signing_secret
from belzakupki_db.models import SearchProfile, Tender, TenderMatch, Tenant
from belzakupki_db.session import get_session

router = APIRouter(prefix="/api/v1", tags=["Integration API v1"])
security = HTTPBearer(auto_error=False)


class ProfileSummary(BaseModel):
    id: int
    name: str


class TenderSummary(BaseModel):
    id: int
    source: str
    external_id: str
    title: str
    customer_name: str | None
    url: str
    deadline_at: datetime | None
    published_at: datetime | None
    estimated_value: str | float | None
    contacts: Any = None


class Opportunity(BaseModel):
    id: int
    updated_at: datetime
    profile: ProfileSummary
    score: float
    relevance_status: Literal["confirmed", "rules_only", "pending", "rejected"]
    eligible: bool
    tender: TenderSummary
    reason: str
    ai_analysis: dict[str, Any] | None


class OpportunityPage(BaseModel):
    items: list[Opportunity]
    next_cursor: str | None
    has_more: bool


def integration_tenant(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session: Session = Depends(get_session),
) -> int:
    expected = os.getenv("INTEGRATION_API_KEY", "")
    tenant_id = os.getenv("INTEGRATION_TENANT_ID", "")
    if len(expected) < 32 or not tenant_id.isdecimal() or int(tenant_id) <= 0:
        raise HTTPException(503, "Integration API is not configured")
    supplied = credentials.credentials if credentials else ""
    if not hmac.compare_digest(hashlib.sha256(supplied.encode()).digest(), hashlib.sha256(expected.encode()).digest()):
        raise HTTPException(401, "Invalid integration credentials", headers={"WWW-Authenticate": "Bearer"})
    tenant = session.get(Tenant, int(tenant_id))
    if tenant is None or not tenant.is_active:
        raise HTTPException(403, "Integration tenant is unavailable")
    return tenant.id


def cursor_after(cursor: str | None, tenant_id: int) -> int:
    if not cursor:
        return 0
    try:
        data = jwt.decode(cursor, signing_secret(), algorithms=["HS256"], audience="opportunities-v1")
        if data["tenant_id"] != tenant_id or type(data["after_id"]) is not int or data["after_id"] < 0:
            raise ValueError("Invalid cursor scope")
        return data["after_id"]
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        raise HTTPException(400, "Invalid cursor") from None


def relevance_status(match: TenderMatch) -> str:
    if match.ai_relevance is False or match.status in {"rejected", "rejected_by_ai"}:
        return "rejected"
    if (match.ai_analysis or {}).get("bypassed"):
        return "rules_only"
    if match.ai_relevance is True:
        return "confirmed"
    return "pending"


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@router.get("/opportunities", response_model=OpportunityPage, operation_id="list_integration_opportunities")
def opportunities(
    cursor: str | None = Query(None, max_length=2048),
    limit: int = Query(100, ge=1, le=100),
    tenant_id: int = Depends(integration_tenant),
    session: Session = Depends(get_session),
) -> OpportunityPage:
    """Reconcile current matches in ID order; after the terminal page restart at null.

    This is a current-state feed, not an append-only event log. Repeated scans
    deliberately include unchanged rows and capture updates to older tenders.
    Consumers must deduplicate by tenant + tender.source + tender.external_id.
    """
    after_id = cursor_after(cursor, tenant_id)
    allowed_profiles = os.getenv("INTEGRATION_PROFILE_IDS", "").strip()
    profile_ids = []
    if allowed_profiles:
        try:
            profile_ids = [int(value.strip()) for value in allowed_profiles.split(",")]
            if any(value <= 0 for value in profile_ids):
                raise ValueError()
        except ValueError:
            raise HTTPException(503, "Invalid integration profile configuration") from None
    stmt = select(TenderMatch).join(TenderMatch.profile)
    if profile_ids:
        stmt = stmt.where(TenderMatch.profile_id.in_(profile_ids))
    rows = list(session.scalars(
        stmt
        .where(SearchProfile.tenant_id == tenant_id, TenderMatch.id > after_id)
        .options(joinedload(TenderMatch.profile), joinedload(TenderMatch.tender).joinedload(Tender.source))
        .order_by(TenderMatch.id).limit(limit + 1)
    ))
    more = len(rows) > limit
    rows = rows[:limit]
    now = datetime.now(timezone.utc)
    items = []
    for match in rows:
        tender = match.tender
        raw = tender.raw_data or {}
        status = relevance_status(match)
        items.append(Opportunity(
            id=match.id, updated_at=max(utc(match.updated_at), utc(tender.updated_at), utc(match.profile.updated_at)),
            profile=ProfileSummary(id=match.profile.id, name=match.profile.name),
            score=float(match.score), relevance_status=status,
            eligible=bool(match.profile.is_active and tender.source.is_active and tender.external_id
                and status in {"confirmed", "rules_only"}
                and match.status not in {"expired", "lost", "won"}
                and tender.status in {"posted", "active", "open", "Подача предложений", "Подача документов/сведений", "Подача предложений / документов"}
                and (tender.deadline_at is None or utc(tender.deadline_at) > now)),
            tender=TenderSummary(
                id=tender.id, source=tender.source.code, external_id=tender.external_id or "",
                title=tender.title, customer_name=tender.customer_name, url=tender.url,
                deadline_at=utc(tender.deadline_at) if tender.deadline_at else None,
                published_at=utc(tender.published_at) if tender.published_at else None,
                estimated_value=raw.get("estimated_value"), contacts=raw.get("contacts"),
            ), reason=match.reason or "", ai_analysis=match.ai_analysis,
        ))
    next_cursor = jwt.encode(
        {"aud": "opportunities-v1", "tenant_id": tenant_id, "after_id": rows[-1].id},
        signing_secret(), algorithm="HS256",
    ) if more else None
    return OpportunityPage(items=items, next_cursor=next_cursor, has_more=more)
