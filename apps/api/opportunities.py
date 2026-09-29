"""Versioned, tenant-scoped current-state feed for independent consumers."""
import hashlib
import hmac
import os
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urljoin, urlparse

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from apps.api.auth import signing_secret
from belzakupki_db.models import SearchProfile, Tender, TenderDocument, TenderMatch, Tenant
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


class CustomerContact(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None


class TenderCustomer(BaseModel):
    name: str | None = None
    unp: str | None = None
    legal_address: str | None = None
    postal_address: str | None = None
    contacts: CustomerContact | None = None


class TenderDocumentLink(BaseModel):
    id: str
    name: str
    source_url: str
    extracted_text: str | None = None
    extracted_text_truncated: bool = False


class TenderDetail(BaseModel):
    source: str
    external_id: str
    source_url: str
    title: str
    description: str | None = None
    source_number: str | None = None
    procedure_type: str | None = None
    status: str | None = None
    published_at: datetime | None = None
    deadline_at: datetime | None = None
    estimated_value: str | float | None = None
    currency: str | None = None
    customer: TenderCustomer
    delivery_terms: str | None = None
    payment_terms: str | None = None
    lots: list[dict[str, Any]]
    objects: list[dict[str, Any]]
    documents: list[TenderDocumentLink]


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


def integration_profile_ids() -> list[int]:
    allowed_profiles = os.getenv("INTEGRATION_PROFILE_IDS", "").strip()
    if not allowed_profiles:
        return []
    try:
        profile_ids = [int(value.strip()) for value in allowed_profiles.split(",")]
        if any(value <= 0 for value in profile_ids):
            raise ValueError()
        return profile_ids
    except ValueError:
        raise HTTPException(503, "Invalid integration profile configuration") from None


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


def _nonempty_text(value: Any) -> str | None:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _mapping_value(mapping: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _nonempty_text(mapping.get(key))
        if value:
            return value
    return None


def _customer_details(tender: Tender) -> TenderCustomer:
    raw = tender.raw_data or {}
    provider_raw = raw.get("raw_data") if isinstance(raw.get("raw_data"), dict) else {}
    organization = next(
        (
            value for value in (
                provider_raw.get("organizator"), provider_raw.get("organizer"),
                raw.get("organizator"), raw.get("organizer"), raw.get("customer"),
            ) if isinstance(value, dict)
        ),
        {},
    )
    contact_data = raw.get("contacts")
    if not isinstance(contact_data, dict):
        contact_data = provider_raw.get("contactOrganizer")
    if not isinstance(contact_data, dict):
        contact_data = organization

    contacts = CustomerContact(
        name=_mapping_value(contact_data, "name", "fullName", "contact_name"),
        phone=_mapping_value(contact_data, "phone", "telephone", "contact_phone"),
        email=_mapping_value(contact_data, "email", "eMail", "contact_email"),
    )
    if not any((contacts.name, contacts.phone, contacts.email)):
        contacts = None

    address = _mapping_value(raw, "legal_address", "address", "location") or _mapping_value(
        organization, "legalAddress", "legal_address", "address", "location"
    )
    return TenderCustomer(
        name=tender.customer_name or _mapping_value(raw, "customer_name") or _mapping_value(organization, "name", "fullName"),
        unp=_mapping_value(raw, "unp", "UNP") or _mapping_value(
            organization, "unp", "UNP", "taxpayerNumber", "taxNumber"
        ),
        legal_address=address,
        postal_address=_mapping_value(raw, "postal_address", "mailing_address") or _mapping_value(
            organization, "postalAddress", "postal_address", "mailingAddress"
        ),
        contacts=contacts,
    )


def _safe_source_url(value: Any, base_url: str) -> str | None:
    candidate = _nonempty_text(value)
    if not candidate:
        return None
    try:
        parsed = urlparse(candidate)
        base = urlparse(base_url)
        candidate_port = parsed.port or 443
        base_port = base.port or 443
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or base.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or base.username is not None
        or base.password is not None
        or not parsed.hostname
        or not base.hostname
        or candidate_port != base_port
    ):
        return None
    candidate_host = parsed.hostname.casefold()
    base_host = base.hostname.casefold()
    if candidate_host != base_host and not candidate_host.endswith(f".{base_host}"):
        return None
    return candidate


EXTRACTED_DOCUMENT_TEXT_LIMIT = 120_000
DOCUMENT_DOWNLOAD_MAX_BYTES = 25 * 1024 * 1024
DOCUMENT_DOWNLOAD_MAX_REDIRECTS = 3


def _document_id(name: str, source_url: str) -> str:
    return hashlib.sha256(f"{name}\0{source_url}".encode()).hexdigest()


def _document_links(tender: Tender, session: Session) -> list[TenderDocumentLink]:
    raw = tender.raw_data or {}
    attachments = raw.get("attachments")
    if not isinstance(attachments, list):
        return []
    extracted_by_name = {
        document.file_name: document.content
        for document in session.scalars(
            select(TenderDocument).where(TenderDocument.tender_id == tender.id)
        )
    }
    documents = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        source_url = _safe_source_url(attachment.get("url"), tender.source.base_url)
        name = _mapping_value(attachment, "name", "file_name", "filename")
        if source_url and name:
            extracted_text = extracted_by_name.get(name)
            documents.append(TenderDocumentLink(
                id=_document_id(name, source_url), name=name, source_url=source_url,
                extracted_text=extracted_text[:EXTRACTED_DOCUMENT_TEXT_LIMIT] if extracted_text else None,
                extracted_text_truncated=bool(extracted_text and len(extracted_text) > EXTRACTED_DOCUMENT_TEXT_LIMIT),
            ))
    return documents


def _provider_download_settings(source_code: str) -> tuple[dict[str, str], bool, str | None]:
    if source_code == "goszakupki_by":
        from worker.sources.goszakupki_by import BASE_URL, build_headers, should_verify_ssl
        return build_headers(), should_verify_ssl(), BASE_URL
    if source_code == "icetrade_by":
        from worker.sources.icetrade_by import BASE_URL, build_headers, should_verify_ssl
        return build_headers(), should_verify_ssl(), BASE_URL
    if source_code == "butb_by":
        from worker.sources.butb_by import BASE_URL, USER_AGENT, should_verify_ssl
        return {"User-Agent": USER_AGENT}, should_verify_ssl(), BASE_URL
    if source_code == "gias_by":
        from worker.sources.gias_by import USER_AGENT, should_verify_ssl
        return {"User-Agent": USER_AGENT}, should_verify_ssl(), None
    return {"User-Agent": "BelZakupki document proxy"}, True, None


def _download_document(source_code: str, source_url: str, source_base_url: str):
    headers, verify_ssl, warmup_url = _provider_download_settings(source_code)
    with httpx.Client(follow_redirects=False, headers=headers, timeout=30, verify=verify_ssl) as client:
        if warmup_url:
            warmup = client.get(warmup_url)
            if warmup.status_code >= 400:
                warmup.raise_for_status()
        current_url = source_url
        for _ in range(DOCUMENT_DOWNLOAD_MAX_REDIRECTS + 1):
            with client.stream("GET", current_url) as upstream:
                if upstream.is_redirect:
                    location = upstream.headers.get("location")
                    next_url = _safe_source_url(urljoin(current_url, location or ""), source_base_url)
                    if not next_url:
                        raise HTTPException(502, "Source document redirect is unavailable")
                    current_url = next_url
                    continue
                upstream.raise_for_status()
                content_length = upstream.headers.get("content-length")
                if content_length and int(content_length) > DOCUMENT_DOWNLOAD_MAX_BYTES:
                    raise HTTPException(413, "Source document exceeds the download limit")
                total = 0
                for chunk in upstream.iter_bytes(chunk_size=64 * 1024):
                    total += len(chunk)
                    if total > DOCUMENT_DOWNLOAD_MAX_BYTES:
                        raise HTTPException(413, "Source document exceeds the download limit")
                    yield chunk
                return
        raise HTTPException(502, "Source document redirected too many times")


def _scoped_tender(
    source_code: str,
    external_id: str,
    tenant_id: int,
    session: Session,
) -> Tender:
    profile_ids = integration_profile_ids()
    match_scope = select(TenderMatch.id).join(TenderMatch.profile).where(
        TenderMatch.tender_id == Tender.id,
        SearchProfile.tenant_id == tenant_id,
    ).correlate(Tender)
    if profile_ids:
        match_scope = match_scope.where(TenderMatch.profile_id.in_(profile_ids))
    tender = session.scalar(
        select(Tender)
        .where(Tender.source.has(code=source_code), Tender.external_id == external_id, match_scope.exists())
        .options(joinedload(Tender.source))
    )
    if tender is None:
        raise HTTPException(404, "Tender is unavailable in this integration scope")
    return tender


@router.get(
    "/tenders/{source_code}/{external_id}",
    response_model=TenderDetail,
    operation_id="get_integration_tender_detail",
)
def tender_detail(
    source_code: str,
    external_id: str,
    tenant_id: int = Depends(integration_tenant),
    session: Session = Depends(get_session),
) -> TenderDetail:
    """Return collector-enriched fields for one tender visible to this consumer.

    Original document bytes remain on their public procurement source. Their
    safe HTTPS links and the collector's bounded extracted text are returned
    here; consumers can request each original through the scoped proxy below.
    """
    tender = _scoped_tender(source_code, external_id, tenant_id, session)
    raw = tender.raw_data or {}
    return TenderDetail(
        source=tender.source.code,
        external_id=tender.external_id or "",
        source_url=tender.url,
        title=tender.title,
        description=tender.description,
        source_number=_mapping_value(raw, "source_number"),
        procedure_type=_mapping_value(raw, "procedure_type"),
        status=tender.status,
        published_at=utc(tender.published_at) if tender.published_at else None,
        deadline_at=utc(tender.deadline_at) if tender.deadline_at else None,
        estimated_value=raw.get("estimated_value"),
        currency=_mapping_value(raw, "currency"),
        customer=_customer_details(tender),
        delivery_terms=_mapping_value(raw, "delivery_terms"),
        payment_terms=_mapping_value(raw, "payment_terms"),
        lots=raw.get("lots") if isinstance(raw.get("lots"), list) else [],
        objects=raw.get("objects") if isinstance(raw.get("objects"), list) else (
            raw.get("lots") if isinstance(raw.get("lots"), list) else []
        ),
        documents=_document_links(tender, session),
    )


@router.get(
    "/tenders/{source_code}/{external_id}/documents/{document_id}",
    operation_id="download_integration_tender_document",
)
def tender_document(
    source_code: str,
    external_id: str,
    document_id: str,
    tenant_id: int = Depends(integration_tenant),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    """Proxy one original attachment without exposing arbitrary outbound URLs."""
    tender = _scoped_tender(source_code, external_id, tenant_id, session)
    document = next(
        (item for item in _document_links(tender, session) if item.id == document_id),
        None,
    )
    if document is None:
        raise HTTPException(404, "Tender document is unavailable in this integration scope")
    safe_name = document.name.replace('"', "'").replace("\n", " ").replace("\r", " ")
    return StreamingResponse(
        _download_document(tender.source.code, document.source_url, tender.source.base_url),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


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
