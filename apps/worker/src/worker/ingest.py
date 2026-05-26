from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
import shutil
import tempfile
from typing import Any
import httpx
from loguru import logger

from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from sqlalchemy.orm import Session

from belzakupki_db.models import SearchProfile, Tender, TenderMatch, TenderSource, TenderResult
from belzakupki_db.enums import MatchStatus
from worker.scoring import score_text
from worker.sources.goszakupki_by import (
    BASE_URL,
    fetch_hvac_vitebsk_tenders,
    fetch_tenders,
)


SOURCE_CODE = "goszakupki_by"
SOURCE_NAME = "goszakupki.by"


@dataclass(frozen=True)
class IngestStats:
    fetched: int
    created: int
    updated: int
    matches: int


def content_hash(value: dict[str, Any]) -> str:
    """Вычисляет SHA-256 хеш содержимого словаря тендера для отслеживания изменений."""
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return sha256(payload.encode("utf-8")).hexdigest()


def get_or_create_source(session: Session, code: str, name: str, base_url: str) -> TenderSource:
    """Возвращает существующий TenderSource из БД или создает его, если он отсутствует.

    Использует savepoint (begin_nested) для безопасной обработки race condition в многопоточной среде.
    """
    source = session.execute(
        select(TenderSource).where(TenderSource.code == code)
    ).scalar_one_or_none()

    if source is not None:
        if source.name != name:
            source.name = name
            session.add(source)
            session.flush()
        return source

    source = TenderSource(
        code=code,
        name=name,
        base_url=base_url,
        is_active=True,
    )
    session.add(source)

    try:
        with session.begin_nested():  # savepoint — откатит только этот INSERT
            session.flush()
    except IntegrityError:
        # Другой воркер уже создал источник — просто читаем его
        source = session.execute(
            select(TenderSource).where(TenderSource.code == code)
        ).scalar_one()

    return source


from datetime import datetime, timezone, timedelta
import re

def parse_deadline_string(deadline_str: str | None) -> datetime | None:
    """Парсит строковое представление даты дедлайна (формат DD.MM.YYYY [HH:MM])

    и преобразует его в UTC datetime, учитывая часовой пояс Минска (UTC+3).
    """
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


def make_json_serializable(d: Any) -> Any:
    """Helper to convert datetimes to ISO format strings for JSON serialization."""
    if isinstance(d, dict):
        return {k: make_json_serializable(v) for k, v in d.items()}
    elif isinstance(d, list):
        return [make_json_serializable(x) for x in d]
    elif isinstance(d, datetime):
        return d.isoformat()
    return d


def upsert_tender(
    session: Session,
    source: TenderSource,
    item: dict[str, Any],
) -> tuple[Tender, bool]:
    """Вставляет новый или обновляет существующий тендер в базе данных.

    Сравнивает хеши контента. Возвращает кортеж (Tender, is_created).
    """
    external_id = str(item["external_id"])
    item_hash = content_hash(item)
    
    deadline_dt = item.get("deadline_at")
    if not deadline_dt:
        deadline_dt = parse_deadline_string(item.get("deadline"))
        
    published_dt = item.get("published_at")

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
            raw_data=make_json_serializable(item),
            content_hash=item_hash,
            deadline_at=deadline_dt,
            published_at=published_dt,
        )
        session.add(tender)
        session.flush()

        return tender, True

    tender.title = item["title"]
    tender.customer_name = item.get("customer_name")
    tender.url = item["url"]
    tender.status = item.get("status", tender.status)
    tender.raw_data = make_json_serializable(item)
    tender.content_hash = item_hash
    tender.deadline_at = deadline_dt
    tender.published_at = published_dt

    return tender, False


def score_tender(session: Session, tender: Tender) -> int:
    """Проводит морфологический скоринг текста тендера по всем активным профилям поиска.

    При совпадении ключевых слов создает или обновляет TenderMatch.
    Возвращает количество созданных/обновленных совпадений.
    """
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
                status=MatchStatus.NEW,
            )
            session.add(match)
        else:
            match.score = result.score
            match.matched_keywords = result.matched_keywords
            match.reason = result.reason

        matches_count += 1

    return matches_count


def enrich_tender_if_needed(
    session: Session,
    tender: Tender,
    was_created: bool,
    matches_count: int,
    source_code: str,
) -> None:
    """Запускает глубокий парсинг страницы тендера при его создании или совпадении с профилем.

    Сливает полученные контакты, условия поставки и лоты в Tender.raw_data.
    """
    if was_created or matches_count > 0:
        try:
            if source_code == "goszakupki_by":
                from worker.sources.goszakupki_by import fetch_tender_details
            elif source_code == "icetrade_by":
                from worker.sources.icetrade_by import fetch_tender_details
            elif source_code == "butb_by":
                from worker.sources.butb_by import fetch_tender_details
            else:
                return

            logger.info(f"Enriching tender details for tender {tender.id} ({tender.url})...")
            details = fetch_tender_details(tender.url)
            
            raw_data = dict(tender.raw_data or {})
            raw_data.update(details)
            tender.raw_data = raw_data
            session.add(tender)
            session.flush()
        except Exception as e:
            logger.warning(f"Failed to enrich tender {tender.id} details: {e}")


def ingest_goszakupki_tenders(
    session: Session,
    *,
    profiles: list[SearchProfile] | None = None,
    limit: int | None = None,
    search_preset: str | None = None,
    commit: bool = True,
) -> IngestStats:
    """Сбор тендеров с goszakupki.by.

    Поддерживает динамический сбор по ключевым словам профилей (profiles),
    предопределенные поиски (search_preset='hvac-vitebsk') или общий список.
    """
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

        if profiles is not None:
            matches_count = score_tender(session, tender)
            matches += matches_count
            enrich_tender_if_needed(session, tender, was_created, matches_count, SOURCE_CODE)

    if profiles is not None:
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
    """Сбор тендеров с icetrade.by.

    Поддерживает динамический сбор по ключевым словам профилей (profiles),
    предопределенные поиски (search_preset='hvac-vitebsk') или общий список.
    """
    from worker.sources.icetrade_by import (
        BASE_URL as ICETRADE_BASE_URL,
        fetch_hvac_vitebsk_tenders as fetch_icetrade_hvac,
        fetch_tenders as fetch_icetrade,
        fetch_dynamic_tenders as fetch_icetrade_dynamic,
    )

    source = get_or_create_source(
        session,
        "icetrade_by",
        "icetrade.by",
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

        if profiles is not None:
            matches_count = score_tender(session, tender)
            matches += matches_count
            enrich_tender_if_needed(session, tender, was_created, matches_count, "icetrade_by")

    if profiles is not None:
        run_ai_analysis_for_new_matches(session, "icetrade_by")

    if commit:
        session.commit()

    return IngestStats(
        fetched=len(items),
        created=created,
        updated=updated,
        matches=matches,
    )


def ingest_butb_tenders(
    session: Session,
    *,
    profiles: list[SearchProfile] | None = None,
    limit: int | None = None,
    commit: bool = True,
) -> IngestStats:
    """Сбор тендеров с БУТБ (zakupki.butb.by)."""
    from worker.sources.butb_by import (
        BASE_URL as BUTB_BASE_URL,
        fetch_tenders as fetch_butb,
        fetch_tenders_for_profiles as fetch_butb_dynamic,
    )

    source = get_or_create_source(
        session,
        "butb_by",
        "butb.by",
        BUTB_BASE_URL,
    )

    if profiles is not None:
        items = fetch_butb_dynamic(profiles, limit=limit)
    else:
        items = fetch_butb(limit=limit)

    created = 0
    updated = 0
    matches = 0

    for item in items:
        tender, was_created = upsert_tender(session, source, item)

        if was_created:
            created += 1
        else:
            updated += 1

        if profiles is not None:
            matches_count = score_tender(session, tender)
            matches += matches_count
            enrich_tender_if_needed(session, tender, was_created, matches_count, "butb_by")

    if profiles is not None:
        run_ai_analysis_for_new_matches(session, "butb_by")

    if commit:
        session.commit()

    return IngestStats(
        fetched=len(items),
        created=created,
        updated=updated,
        matches=matches,
    )


def ingest_gias_tenders(
    session: Session,
    *,
    profiles: list[SearchProfile] | None = None,
    limit: int | None = None,
    commit: bool = True,
) -> IngestStats:
    """Сбор тендеров с ГИАС (gias.by)."""
    from worker.sources.gias_by import (
        BASE_URL as GIAS_BASE_URL,
        fetch_tenders as fetch_gias,
        fetch_tenders_for_profiles as fetch_gias_dynamic,
    )

    source = get_or_create_source(
        session,
        "gias_by",
        "gias.by",
        GIAS_BASE_URL,
    )

    if profiles is not None:
        items = fetch_gias_dynamic(profiles, limit=limit)
    else:
        items = fetch_gias(limit=limit)

    created = 0
    updated = 0
    matches = 0

    for item in items:
        tender, was_created = upsert_tender(session, source, item)

        if was_created:
            created += 1
        else:
            updated += 1

        if profiles is not None:
            matches_count = score_tender(session, tender)
            matches += matches_count

    if profiles is not None:
        run_ai_analysis_for_new_matches(session, "gias_by")

    if commit:
        session.commit()

    return IngestStats(
        fetched=len(items),
        created=created,
        updated=updated,
        matches=matches,
    )


def run_ai_analysis_for_new_matches(session: Session, source_code: str) -> None:
    """Запускает двухэтапную ИИ-проверку релевантности тендеров через DeepSeek API.

    Этап 1: Экспресс-анализ метаданных (название, описание, заказчик). Если не подходит -> отклонение.
    Этап 2: Скачивание вложений (.pdf, .docx, .xlsx), извлечение текста и глубокий анализ требований/бюджета.
    """
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

    _custom_temp_dir = os.getenv("WORKER_TEMP_DIR")
    temp_dir = _custom_temp_dir or tempfile.mkdtemp(prefix="belzakupki_docs_")
    _temp_dir_managed = not _custom_temp_dir  # True = мы создали, мы и удалим
    if _custom_temp_dir:
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
    elif source_code == "butb_by":
        from worker.sources.butb_by import fetch_tender_attachments
    elif source_code == "gias_by":
        fetch_tender_attachments = lambda url: []
    else:
        logger.error(f"Unknown source code: {source_code}")
        return

    from belzakupki_db.presets import PRESETS

    for match in matches:
        tender = match.tender
        logger.info(f"AI Analyzing match {match.id} (Tender: {tender.title})")

        profile = match.profile
        default_hvac = PRESETS["hvac"]["description"]
        niche_description = profile.niche_description or default_hvac
        keywords = profile.keywords or []
        negative_keywords = profile.negative_keywords or []

        try:
            # Stage 1: Metadata-based relevance check
            metadata_analysis = analyze_relevance_by_metadata(
                title=tender.title,
                customer=tender.customer_name or "Не указан",
                niche_description=niche_description,
                keywords=keywords,
                negative_keywords=negative_keywords,
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
                match.status = MatchStatus.REJECTED_BY_AI
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
                        elif source_code == "butb_by":
                            from worker.sources.butb_by import should_verify_ssl, USER_AGENT
                            verify = should_verify_ssl()
                            headers = {"User-Agent": USER_AGENT}
                        else:
                            from worker.sources.icetrade_by import build_headers, should_verify_ssl
                            verify = should_verify_ssl()
                            headers = build_headers()

                        with httpx.Client(follow_redirects=True, headers=headers, verify=verify, timeout=20) as client:
                            if source_code == "goszakupki_by":
                                client.get("https://goszakupki.by")
                            elif source_code == "butb_by":
                                client.get("https://zakupki.butb.by/")
                            
                            MAX_SIZE_LIMIT = 15 * 1024 * 1024
                            with client.stream("GET", file_url) as r:
                                r.raise_for_status()
                                content_length = r.headers.get("Content-Length")
                                if content_length and int(content_length) > MAX_SIZE_LIMIT:
                                    raise ValueError(f"File size exceeds limit: {content_length} bytes")
                                
                                total_bytes = 0
                                with open(local_path, "wb") as f:
                                    for chunk in r.iter_bytes(chunk_size=8192):
                                        total_bytes += len(chunk)
                                        if total_bytes > MAX_SIZE_LIMIT:
                                            raise ValueError("File size exceeded limit of 15 MB during download")
                                        f.write(chunk)

                        file_text = extract_text_from_file(local_path)
                        if file_text:
                            text_parts.append(f"--- File: {file_name} ---\n{file_text}")
                            
                            from belzakupki_db.models import TenderDocument
                            # Save to TenderDocument, update if already exists
                            doc = session.query(TenderDocument).filter(
                                TenderDocument.tender_id == tender.id,
                                TenderDocument.file_name == file_name
                            ).first()
                            if doc:
                                doc.content = file_text
                            else:
                                doc = TenderDocument(
                                    tender_id=tender.id,
                                    file_name=file_name,
                                    content=file_text
                                )
                                session.add(doc)
                            session.flush()
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
                niche_description=niche_description,
                keywords=keywords,
                negative_keywords=negative_keywords,
            )

            if analysis is not None:
                match.ai_relevance = analysis.get("relevant", False)
                match.ai_analysis = analysis
                if not match.ai_relevance:
                    logger.info(f"Tender {tender.id} rejected by AI. Setting status to 'rejected_by_ai'.")
                    match.status = MatchStatus.REJECTED_BY_AI
                else:
                    logger.info(f"Tender {tender.id} approved by AI. Keeping status 'new'.")
            else:
                logger.warning(f"DeepSeek analysis returned None for match {match.id}")

            session.add(match)
            session.flush()

        except Exception as e:
            logger.error(f"Error during AI analysis of match {match.id}: {e}")

    if _temp_dir_managed:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


def check_results_for_active_tenders(session: Session) -> None:
    """Проверяет результаты прошедших тендеров, у которых наступил дедлайн, и обновляет их статусы."""
    from datetime import datetime, timezone
    import worker.sources.goszakupki_by as gk
    import worker.sources.icetrade_by as it

    now = datetime.now(timezone.utc)
    
    # Ищем тендеры с прошедшим дедлайном, которые не находятся в конечном статусе
    completed_statuses = ["closed", "canceled", "manque", "завершен", "отменен", "не состоялся", "признан несостоявшимся", "отменена"]
    
    stmt = (
        select(Tender)
        .outerjoin(TenderResult)
        .where(TenderResult.id == None)
        .where(Tender.deadline_at < now)
        .where(Tender.status.notin_(completed_statuses))
    )
    
    active_tenders = session.scalars(stmt).all()
    logger.info(f"Found {len(active_tenders)} active expired tenders to check for results.")
    
    for tender in active_tenders:
        logger.info(f"Checking results for tender {tender.id} ({tender.url})...")
        try:
            result_data = None
            if "goszakupki.by" in tender.url:
                result_data = gk.fetch_tender_result(tender.url)
            elif "icetrade.by" in tender.url:
                result_data = it.fetch_tender_result(tender.url)
                
            if result_data:
                tender_status = result_data.get("status", "Состоялась")
                tender.status = tender_status
                
                # Convert Decimal to float for JSON compatibility in raw_result_data
                from decimal import Decimal
                raw_result_data = dict(result_data)
                if isinstance(raw_result_data.get("contract_price"), Decimal):
                    raw_result_data["contract_price"] = float(raw_result_data["contract_price"])
                
                # Сохраняем или обновляем результат закупки
                res_stmt = select(TenderResult).where(TenderResult.tender_id == tender.id)
                db_result = session.scalars(res_stmt).first()
                
                if not db_result:
                    db_result = TenderResult(
                        tender_id=tender.id,
                        status=tender_status,
                        winner_name=result_data.get("winner_name"),
                        winner_unp=result_data.get("winner_unp"),
                        contract_price=result_data.get("contract_price"),
                        currency=result_data.get("currency"),
                        raw_result_data=raw_result_data
                    )
                    session.add(db_result)
                else:
                    db_result.status = tender_status
                    db_result.winner_name = result_data.get("winner_name")
                    db_result.winner_unp = result_data.get("winner_unp")
                    db_result.contract_price = result_data.get("contract_price")
                    db_result.currency = result_data.get("currency")
                    db_result.raw_result_data = raw_result_data
                
                session.flush()
                logger.info(f"Successfully saved result for tender {tender.id}: status={tender_status}, winner={db_result.winner_name}, price={db_result.contract_price}")
            else:
                logger.info(f"No result protocol found yet for tender {tender.id} ({tender.url})")
        except Exception as e:
            logger.error(f"Failed to check results for tender {tender.id}: {e}")
            
    session.commit()

