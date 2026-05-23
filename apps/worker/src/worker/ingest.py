from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from typing import Any
import httpx
from loguru import logger

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


def get_or_create_source(session: Session, code: str, name: str, base_url: str) -> TenderSource:
    source = session.execute(
        select(TenderSource).where(TenderSource.code == code)
    ).scalar_one_or_none()

    if source is not None:
        return source

    source = TenderSource(
        code=code,
        name=name,
        base_url=base_url,
        is_active=True,
    )
    session.add(source)

    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        source = session.execute(
            select(TenderSource).where(TenderSource.code == code)
        ).scalar_one()

    return source


from datetime import datetime, timezone, timedelta
import re

def parse_deadline_string(deadline_str: str | None) -> datetime | None:
    if not deadline_str:
        return None
        
    match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2}))?", deadline_str)
    if not match:
        return None
        
    day, month, year, hour, minute = match.groups()
    hour_val = int(hour) if hour else 23
    min_val = int(minute) if minute else 59
    
    try:
        tz_minsk = timezone(timedelta(hours=3))
        dt = datetime(int(year), int(month), int(day), hour_val, min_val, tzinfo=tz_minsk)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def upsert_tender(
    session: Session,
    source: TenderSource,
    item: dict[str, Any],
) -> tuple[Tender, bool]:
    external_id = str(item["external_id"])
    item_hash = content_hash(item)
    deadline_dt = parse_deadline_string(item.get("deadline"))

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
            deadline_at=deadline_dt,
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
    tender.deadline_at = deadline_dt

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

        min_score = profile.min_score or 0.0
        if result.score <= 0 or result.score < min_score:
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
    profiles: list[SearchProfile] | None = None,
    limit: int | None = None,
    search_preset: str | None = None,
    commit: bool = True,
) -> IngestStats:
    source = get_or_create_source(session, SOURCE_CODE, SOURCE_NAME, BASE_URL)

    if profiles is not None:
        from worker.sources.goszakupki_by import fetch_dynamic_tenders
        items = fetch_dynamic_tenders(profiles, limit=limit)
    elif search_preset == "hvac-vitebsk":
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

    run_ai_analysis_for_new_matches(session, SOURCE_CODE)

    if commit:
        session.commit()

    return IngestStats(
        fetched=len(items),
        created=created,
        updated=updated,
        matches=matches,
    )


def ingest_icetrade_tenders(
    session: Session,
    *,
    profiles: list[SearchProfile] | None = None,
    limit: int | None = None,
    search_preset: str | None = None,
    commit: bool = True,
) -> IngestStats:
    from worker.sources.icetrade_by import (
        BASE_URL as ICETRADE_BASE_URL,
        fetch_hvac_vitebsk_tenders as fetch_icetrade_hvac,
        fetch_tenders as fetch_icetrade,
        fetch_dynamic_tenders as fetch_icetrade_dynamic,
    )

    source = get_or_create_source(
        session,
        "icetrade_by",
        "ИС Тендеры (icetrade.by)",
        ICETRADE_BASE_URL,
    )

    if profiles is not None:
        items = fetch_icetrade_dynamic(profiles, limit=limit)
    elif search_preset == "hvac-vitebsk":
        items = fetch_icetrade_hvac(limit=limit)
    elif search_preset is None:
        items = fetch_icetrade(limit=limit)
    else:
        raise ValueError(f"Unknown icetrade search preset: {search_preset}")

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

    run_ai_analysis_for_new_matches(session, "icetrade_by")

    if commit:
        session.commit()

    return IngestStats(
        fetched=len(items),
        created=created,
        updated=updated,
        matches=matches,
    )


def run_ai_analysis_for_new_matches(session: Session, source_code: str) -> None:
    token = os.getenv("DEEPSEEK_TOKEN")
    if not token or token == "your-deepseek-token":
        logger.info("DEEPSEEK_TOKEN not configured. Skipping AI analysis.")
        return

    # Find matches that are 'new' and don't have AI relevance set yet
    stmt = (
        select(TenderMatch)
        .join(TenderMatch.tender)
        .join(Tender.source)
        .where(
            TenderSource.code == source_code,
            TenderMatch.status == "new",
            TenderMatch.ai_relevance.is_(None),
        )
    )
    matches = list(session.execute(stmt).scalars())
    if not matches:
        return

    logger.info(f"Running AI analysis for {len(matches)} new matches from source '{source_code}'...")

    temp_dir = "/app/apps/worker/temp_docs" if os.path.exists("/app") else "/Users/maksimkorotov/Documents/belzakupki/apps/worker/temp_docs"
    os.makedirs(temp_dir, exist_ok=True)

    from worker.analyzer.text_extractor import extract_text_from_file
    from worker.analyzer.deepseek_client import (
        analyze_relevance_by_metadata,
        analyze_tender_relevance,
    )

    if source_code == "goszakupki_by":
        from worker.sources.goszakupki_by import fetch_tender_attachments
    elif source_code == "icetrade_by":
        from worker.sources.icetrade_by import fetch_tender_attachments
    else:
        logger.error(f"Unknown source code: {source_code}")
        return

    for match in matches:
        tender = match.tender
        logger.info(f"AI Analyzing match {match.id} (Tender: {tender.title})")

        try:
            # Stage 1: Metadata-based relevance check
            metadata_analysis = analyze_relevance_by_metadata(
                title=tender.title,
                customer=tender.customer_name or "Не указан",
                description=tender.description,
            )

            if metadata_analysis is None:
                logger.warning(f"DeepSeek metadata analysis returned None for match {match.id}. Skipping for now.")
                continue

            is_relevant = metadata_analysis.get("relevant", False)
            if not is_relevant:
                logger.info(f"Tender {tender.id} rejected by AI Stage 1 (metadata). Explanation: {metadata_analysis.get('explanation')}")
                match.ai_relevance = False
                match.ai_analysis = {
                    "relevant": False,
                    "explanation": metadata_analysis.get("explanation", "Отклонено на этапе проверки метаданных"),
                    "stage": 1
                }
                match.status = "rejected_by_ai"
                session.add(match)
                session.flush()
                continue

            # Stage 2: Deep check with documents
            # 1. Fetch attachments
            attachments = fetch_tender_attachments(tender.url)
            logger.info(f"Found {len(attachments)} attachments for tender {tender.id}")

            raw_data = dict(tender.raw_data or {})
            raw_data["attachments"] = attachments
            tender.raw_data = raw_data
            session.add(tender)

            text_content = ""
            if not attachments:
                logger.info(f"No attachments found for tender {tender.id}. Analyzing description/title.")
                text_content = tender.description or tender.title
            else:
                text_parts = []
                for idx, att in enumerate(attachments):
                    file_name = att["name"]
                    file_url = att["url"]

                    clean_name = "".join(c for c in file_name if c.isalnum() or c in (".", "_", "-")).strip()
                    if not clean_name:
                        clean_name = f"doc_{idx}"

                    local_path = os.path.join(temp_dir, f"{tender.id}_{idx}_{clean_name}")

                    # Download
                    try:
                        if source_code == "goszakupki_by":
                            from worker.sources.goszakupki_by import build_headers, should_verify_ssl
                            verify = should_verify_ssl()
                            headers = build_headers()
                        else:
                            from worker.sources.icetrade_by import build_headers, should_verify_ssl
                            verify = should_verify_ssl()
                            headers = build_headers()

                        with httpx.Client(follow_redirects=True, headers=headers, verify=verify, timeout=20) as client:
                            if source_code == "goszakupki_by":
                                client.get("https://goszakupki.by")
                            response = client.get(file_url)
                            response.raise_for_status()
                            with open(local_path, "wb") as f:
                                f.write(response.content)

                        file_text = extract_text_from_file(local_path)
                        if file_text:
                            text_parts.append(f"--- File: {file_name} ---\n{file_text}")
                    except Exception as e:
                        logger.warning(f"Failed to download/extract file {file_name}: {e}")
                    finally:
                        if os.path.exists(local_path):
                            os.remove(local_path)

                text_content = "\n\n".join(text_parts)

            # Analyze
            analysis = analyze_tender_relevance(
                title=tender.title,
                customer=tender.customer_name or "Не указан",
                documents_text=text_content or tender.title,
            )

            if analysis is not None:
                match.ai_relevance = analysis.get("relevant", False)
                match.ai_analysis = analysis
                if not match.ai_relevance:
                    logger.info(f"Tender {tender.id} rejected by AI. Setting status to 'rejected_by_ai'.")
                    match.status = "rejected_by_ai"
                else:
                    logger.info(f"Tender {tender.id} approved by AI. Keeping status 'new'.")
            else:
                logger.warning(f"DeepSeek analysis returned None for match {match.id}")

            session.add(match)
            session.flush()

        except Exception as e:
            logger.error(f"Error during AI analysis of match {match.id}: {e}")

    try:
        if os.path.exists(temp_dir):
            os.rmdir(temp_dir)
    except Exception:
        pass
