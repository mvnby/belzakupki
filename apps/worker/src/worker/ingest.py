from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from sqlalchemy.orm import Session

from belzakupki_db.models import SearchProfile, Tender, TenderMatch, TenderSource
from worker.scoring import score_text
from worker.sources.goszakupki_by import (
    BASE_URL,
    fetch_hvac_vitebsk_tenders,
    fetch_tenders,
)


SOURCE_CODE = "goszakupki_by"
SOURCE_NAME = "Госзакупки Беларуси"


@dataclass(frozen=True)
class IngestStats:
    fetched: int
    created: int
    updated: int
    matches: int


def content_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return sha256(payload.encode("utf-8")).hexdigest()


def get_or_create_source(session: Session) -> TenderSource:
    source = session.execute(
        select(TenderSource).where(TenderSource.code == SOURCE_CODE)
    ).scalar_one_or_none()

    if source is not None:
        return source

    source = TenderSource(
        code=SOURCE_CODE,
        name=SOURCE_NAME,
        base_url=BASE_URL,
        is_active=True,
    )
    session.add(source)

    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        source = session.execute(
            select(TenderSource).where(TenderSource.code == SOURCE_CODE)
        ).scalar_one()

    return source


def upsert_tender(
    session: Session,
    source: TenderSource,
    item: dict[str, Any],
) -> tuple[Tender, bool]:
    external_id = str(item["external_id"])
    item_hash = content_hash(item)

    tender = session.execute(
        select(Tender).where(
            Tender.source_id == source.id,
            Tender.external_id == external_id,
        )
    ).scalar_one_or_none()

    if tender is None:
        tender = Tender(
            source_id=source.id,
            external_id=external_id,
            title=item["title"],
            customer_name=item.get("customer_name"),
            url=item["url"],
            status=item.get("status", "posted"),
            raw_data=item,
            content_hash=item_hash,
        )
        session.add(tender)
        session.flush()

        return tender, True

    tender.title = item["title"]
    tender.customer_name = item.get("customer_name")
    tender.url = item["url"]
    tender.status = item.get("status", tender.status)
    tender.raw_data = item
    tender.content_hash = item_hash

    return tender, False


def score_tender(session: Session, tender: Tender) -> int:
    profiles = session.execute(
        select(SearchProfile).where(SearchProfile.is_active.is_(True))
    ).scalars()

    matches_count = 0
    text = " ".join(
        value
        for value in (
            tender.title,
            tender.description,
            tender.customer_name,
        )
        if value
    )

    for profile in profiles:
        result = score_text(text, profile.keywords, profile.negative_keywords)

        if result.score <= 0:
            continue

        match = session.execute(
            select(TenderMatch).where(
                TenderMatch.tender_id == tender.id,
                TenderMatch.profile_id == profile.id,
            )
        ).scalar_one_or_none()

        if match is None:
            match = TenderMatch(
                tender_id=tender.id,
                profile_id=profile.id,
                score=result.score,
                matched_keywords=result.matched_keywords,
                reason=result.reason,
                status="new",
            )
            session.add(match)
        else:
            match.score = result.score
            match.matched_keywords = result.matched_keywords
            match.reason = result.reason

        matches_count += 1

    return matches_count


def ingest_goszakupki_tenders(
    session: Session,
    *,
    limit: int | None = None,
    search_preset: str | None = None,
    commit: bool = True,
) -> IngestStats:
    source = get_or_create_source(session)

    if search_preset == "hvac-vitebsk":
        items = fetch_hvac_vitebsk_tenders(limit=limit)
    elif search_preset is None:
        items = fetch_tenders(limit=limit)
    else:
        raise ValueError(f"Unknown goszakupki search preset: {search_preset}")

    created = 0
    updated = 0
    matches = 0

    for item in items:
        tender, was_created = upsert_tender(session, source, item)

        if was_created:
            created += 1
        else:
            updated += 1

        matches += score_tender(session, tender)

    if commit:
        session.commit()

    return IngestStats(
        fetched=len(items),
        created=created,
        updated=updated,
        matches=matches,
    )
