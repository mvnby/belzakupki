from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session
from belzakupki_db.models import Tender
from worker.ingest import score_tender, enrich_tender_if_needed
from worker.resource_limits import positive_int_env


ROUTING_BATCH_SIZE = positive_int_env("WORKER_ROUTING_BATCH_SIZE", 100)

def run_local_profile_routing(session: Session) -> int:
    """
    Проверяет все новые/необработанные тендеры по активным поисковым профилям.
    При совпадении создает TenderMatch.
    В конце помечает тендеры как проверенные (is_matched_checked = True).
    Обогащение деталями (lots, contacts, etc.) выполняется в отдельных транзакциях.
    """
    stmt = (
        select(Tender)
        .where(Tender.is_matched_checked.is_(False))
        .order_by(Tender.id.asc())
        .limit(ROUTING_BATCH_SIZE)
    )
    unchecked_tenders = list(session.execute(stmt).scalars())
    
    if not unchecked_tenders:
        logger.info("No unchecked tenders for local routing.")
        return 0
        
    logger.info(f"Routing {len(unchecked_tenders)} unchecked tenders...")
    matched_tenders = []
    matched_count = 0
    
    for tender in unchecked_tenders:
        # score_tender проверяет по всем активным профилям и возвращает количество совпадений
        matches_count = score_tender(session, tender)
        
        if matches_count > 0:
            matched_count += matches_count
            source_code = tender.source.code if tender.source else "goszakupki_by"
            matched_tenders.append((tender.id, matches_count, source_code))
            
        tender.is_matched_checked = True
        session.add(tender)
        
    # Сначала коммитим проверку и создание совпадений (быстрая операция без сети)
    session.commit()
    
    # Теперь обогащаем деталями совпавшие тендеры в изолированных транзакциях
    if matched_tenders:
        logger.info(f"Enriching details for {len(matched_tenders)} matched tenders...")
        for tender_id, matches_count, source_code in matched_tenders:
            try:
                # Получаем свежий объект в текущей транзакции
                tender = session.get(Tender, tender_id)
                if tender:
                    enrich_tender_if_needed(session, tender, was_created=True, matches_count=matches_count, source_code=source_code)
                    session.commit()
            except Exception as e:
                session.rollback()
                logger.warning(f"Failed to enrich matched tender {tender_id} details: {e}")
        
    logger.info(f"Local routing complete. Matched {matched_count} profiles.")
    return matched_count
