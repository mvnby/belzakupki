from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session, joinedload

from belzakupki_db.models import Tender, TenderMatch, SearchProfile


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None

    return value.isoformat()


def _decimal_to_float(value: Decimal | None) -> float | None:
    if value is None:
        return None

    return float(value)


def serialize_tender(tender: Tender, tenant_id: int | None = None) -> dict[str, Any]:
    """Преобразует объект модели Tender в словарь для API-ответа.

    Включает в себя информацию об источнике, дедлайнах и результатах ИИ-анализа (если есть).
    """
    raw_data = tender.raw_data or {}

    ai_relevance = None
    ai_analysis = None
    if tender.matches:
        for match in tender.matches:
            if tenant_id is not None and match.profile.tenant_id != tenant_id:
                continue
            if match.ai_analysis is not None:
                ai_relevance = match.ai_relevance
                ai_analysis = match.ai_analysis
                break

    result_data = None
    if tender.result:
        result_data = {
            "status": tender.result.status,
            "winner_name": tender.result.winner_name,
            "winner_unp": tender.result.winner_unp,
            "contract_price": _decimal_to_float(tender.result.contract_price),
            "currency": tender.result.currency,
            "participants": tender.result.raw_result_data.get("participants", []) if tender.result.raw_result_data else [],
            "result_url": tender.result.raw_result_data.get("result_url") if tender.result.raw_result_data else None,
            "protocol_url": tender.result.raw_result_data.get("protocol_url") if tender.result.raw_result_data else None
        }

    return {
        "id": tender.id,
        "source": tender.source.code if tender.source else None,
        "source_name": tender.source.name if tender.source else None,
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
        "attachments": raw_data.get("attachments") or [],
        "contacts": raw_data.get("contacts"),
        "delivery_terms": raw_data.get("delivery_terms"),
        "payment_terms": raw_data.get("payment_terms"),
        "lots": raw_data.get("lots") or [],
        "ai_relevance": ai_relevance,
        "ai_analysis": ai_analysis,
        "result": result_data,
    }



def serialize_match(match: TenderMatch) -> dict[str, Any]:
    """Преобразует объект совпадения TenderMatch в словарь для API-ответа.

    Включает информацию о профиле поиска, ключевых словах, скоринге, ИИ-анализе и самом тендере.
    """
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
        "ai_relevance": match.ai_relevance,
        "ai_analysis": match.ai_analysis,
        "crm_deal_id": match.crm_deal_id,
        "tender": serialize_tender(match.tender, tenant_id=match.profile.tenant_id),
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
    """Возвращает список тендеров с сортировкой по дате создания (убывание).

    Поддерживает пагинацию (limit, offset), фильтрацию только совпавших тендеров (matched_only)
    и поиск по текстовой строке в названии, заказчике или внешнем ID (query).
    """
    stmt: Select[tuple[Tender]] = (
        select(Tender)
        .options(
            joinedload(Tender.source),
            joinedload(Tender.result)
        )
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
    """Возвращает один тендер по его ID с предзагрузкой связей (источник, совпадения)."""
    return session.execute(
        select(Tender)
        .options(
            joinedload(Tender.source),
            joinedload(Tender.matches),
            joinedload(Tender.result),
        )
        .where(Tender.id == tender_id)
    ).unique().scalar_one_or_none()




def list_matches(
    session: Session,
    *,
    limit: int = 20,
    offset: int = 0,
    profile_id: int | None = None,
    status: str | None = None,
    tenant_id: int | None = None,
) -> list[TenderMatch]:
    """Возвращает список совпадений тендеров, отсортированных по баллу релевантности (убывание).

    Используется для вывода в панель управления. Eager-loads профиль и тендер с его источником.
    """
    stmt = (
        select(TenderMatch)
        .options(
            joinedload(TenderMatch.profile),
            joinedload(TenderMatch.tender).joinedload(Tender.source),
            joinedload(TenderMatch.tender).joinedload(Tender.result),
        )
    )

    if tenant_id is not None:
        stmt = stmt.join(TenderMatch.profile).where(SearchProfile.tenant_id == tenant_id)

    if profile_id is not None:
        stmt = stmt.where(TenderMatch.profile_id == profile_id)

    if status is not None:
        if status == "new_processed":
            stmt = stmt.where(TenderMatch.status.in_(["new", "processed"]))
        else:
            stmt = stmt.where(TenderMatch.status == status)

    stmt = stmt.order_by(
        TenderMatch.created_at.desc(),
        TenderMatch.score.desc(),
        TenderMatch.id.desc(),
    )

    return list(session.execute(stmt.limit(limit).offset(offset)).scalars())
