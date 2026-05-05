from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session, joinedload

from belzakupki_db.models import Tender, TenderMatch


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None

    return value.isoformat()


def _decimal_to_float(value: Decimal | None) -> float | None:
    if value is None:
        return None

    return float(value)


def serialize_tender(tender: Tender) -> dict[str, Any]:
    raw_data = tender.raw_data or {}

    return {
        "id": tender.id,
        "source": tender.source.code if tender.source else None,
        "external_id": tender.external_id,
        "source_number": raw_data.get("source_number"),
        "title": tender.title,
        "customer_name": tender.customer_name,
        "url": tender.url,
        "status": tender.status,
        "procedure_type": raw_data.get("procedure_type"),
        "deadline": raw_data.get("deadline"),
        "estimated_value": raw_data.get("estimated_value"),
        "search": raw_data.get("search"),
        "search_text": raw_data.get("search_text"),
        "search_regions": raw_data.get("search_regions") or [],
        "search_industry": raw_data.get("search_industry"),
        "published_at": _isoformat(tender.published_at),
        "deadline_at": _isoformat(tender.deadline_at),
        "created_at": _isoformat(tender.created_at),
        "updated_at": _isoformat(tender.updated_at),
    }


def serialize_match(match: TenderMatch) -> dict[str, Any]:
    return {
        "id": match.id,
        "score": _decimal_to_float(match.score),
        "matched_keywords": match.matched_keywords,
        "reason": match.reason,
        "status": match.status,
        "profile": {
            "id": match.profile.id,
            "name": match.profile.name,
        },
        "tender": serialize_tender(match.tender),
        "created_at": _isoformat(match.created_at),
        "updated_at": _isoformat(match.updated_at),
    }


def list_tenders(
    session: Session,
    *,
    limit: int = 20,
    offset: int = 0,
    matched_only: bool = False,
    query: str | None = None,
) -> list[Tender]:
    stmt: Select[tuple[Tender]] = (
        select(Tender)
        .options(joinedload(Tender.source))
        .order_by(Tender.created_at.desc(), Tender.id.desc())
    )

    if matched_only:
        stmt = stmt.join(Tender.matches).distinct()

    if query:
        pattern = f"%{query}%"
        stmt = stmt.where(
            or_(
                Tender.title.ilike(pattern),
                Tender.customer_name.ilike(pattern),
                Tender.external_id.ilike(pattern),
            )
        )

    return list(session.execute(stmt.limit(limit).offset(offset)).scalars())


def get_tender(session: Session, tender_id: int) -> Tender | None:
    return session.execute(
        select(Tender)
        .options(joinedload(Tender.source))
        .where(Tender.id == tender_id)
    ).scalar_one_or_none()


def list_matches(
    session: Session,
    *,
    limit: int = 20,
    offset: int = 0,
) -> list[TenderMatch]:
    stmt = (
        select(TenderMatch)
        .options(
            joinedload(TenderMatch.profile),
            joinedload(TenderMatch.tender).joinedload(Tender.source),
        )
        .order_by(
            TenderMatch.score.desc(),
            TenderMatch.created_at.desc(),
            TenderMatch.id.desc(),
        )
    )

    return list(session.execute(stmt.limit(limit).offset(offset)).scalars())
