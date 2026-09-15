from __future__ import annotations

from datetime import datetime, timezone
import html
import os
import time
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from belzakupki_db.models import NotificationChannel, NotificationLog, TenderMatch, Tender, SearchProfile
from belzakupki_db.enums import MatchStatus, NotificationStatus
from worker.resource_limits import positive_int_env


NOTIFICATION_BATCH_SIZE = positive_int_env("WORKER_NOTIFICATION_BATCH_SIZE", 50)


def send_telegram_message(bot_token: str, chat_id: str, text: str, reply_markup: dict | None = None) -> None:
    """Выполняет прямой POST-запрос к Telegram Bot API для отправки сообщения.

    Поддерживает HTML-разметку и инлайн-клавиатуру reply_markup.
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    
    logger.info(f"Sending Telegram notification to chat_id={chat_id}")
    
    response = httpx.post(url, json=payload, timeout=10)
    
    if response.status_code != 200:
        logger.error(f"Failed to send Telegram message: {response.text}")
        response.raise_for_status()


def format_tender_message(match: TenderMatch) -> str:
    """Форматирует HTML-текст сообщения для Telegram.

    Сюда включаются метаданные тендера (заказчик, стоимость, дедлайн)
    и выжимка из ИИ-анализа (объем работ, требования, бюджет).
    """
    tender = match.tender
    profile = match.profile
    
    raw_data = tender.raw_data or {}
    
    title = html.escape(tender.title)
    customer = html.escape(tender.customer_name or "Не указан")
    source_name = html.escape(tender.source.name if tender.source else "Неизвестный источник")
    profile_name = html.escape(profile.name)
    keywords = html.escape(", ".join(match.matched_keywords))
    
    estimated_value = html.escape(raw_data.get("estimated_value") or "Не указана")
    deadline = html.escape(raw_data.get("deadline") or "Не указан")
    
    url = tender.url
    
    # AI Analysis summary
    ai_summary = ""
    if match.ai_relevance and match.ai_analysis:
        info = match.ai_analysis.get("commercial_proposal_info", {})
        scope = info.get("scope", "")
        reqs = info.get("requirements", "")
        budget = info.get("budget_notes", "")
        
        ai_parts = [
            "",
            "🤖 <b>Анализ ИИ (DeepSeek):</b>",
        ]
        if scope:
            ai_parts.append(f"📝 <b>Объем:</b> {html.escape(scope)}")
        if reqs:
            ai_parts.append(f"🛡️ <b>Требования:</b> {html.escape(reqs)}")
        if budget:
            ai_parts.append(f"💵 <b>Бюджет/Оплата:</b> {html.escape(budget)}")
            
        ai_summary = "\n".join(ai_parts)
    
    message_lines = [
        "🔔 <b>Найден подходящий тендер!</b>",
        "",
        f"📄 <b>Название:</b> {title}",
        f"🏢 <b>Заказчик:</b> {customer}",
        f"🌐 <b>Источник:</b> {source_name}",
        f"🎯 <b>Профиль поиска:</b> {profile_name} (Скоринг: {match.score})",
        f"🏷️ <b>Ключевые слова:</b> {keywords}",
        f"💰 <b>Стоимость:</b> {estimated_value}",
        f"⏳ <b>Дедлайн подачи:</b> {deadline}",
        ai_summary,
        "",
        f"🔗 <a href=\"{url}\">Открыть тендер на первоисточнике</a>",
    ]
    
    return "\n".join([line for line in message_lines if line is not None])


def _dispatch_notification_batch(
    session: Session,
    tenant_id: int | None = None,
) -> tuple[int, int]:
    """Извлекает из базы данных новые совпадения и рассылает их по каналам уведомлений.

    - Исключает совпадения, забракованные ИИ на этапе экспресс-анализа.
    - Исключает тендеры, у которых истек дедлайн подачи заявок.
    - Для каждого активного канала (например, Telegram) отправляет сообщение с инлайн-кнопками.
    - Фиксирует факты отправки в таблице notification_logs.
    - Переводит статус совпадения в 'processed'.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    
    # Находим все совпадения со статусом 'new'
    stmt = (
        select(TenderMatch)
        .options(
            joinedload(TenderMatch.tender).joinedload(Tender.source),
            joinedload(TenderMatch.profile),
        )
        .where(
            TenderMatch.status == MatchStatus.NEW,
            TenderMatch.ai_relevance.is_(True),
        )
        .order_by(TenderMatch.created_at.asc())
        .limit(NOTIFICATION_BATCH_SIZE)
    )
    if tenant_id is not None:
        stmt = stmt.join(TenderMatch.profile).where(SearchProfile.tenant_id == tenant_id)

    matches = list(session.execute(stmt).scalars())
    
    if not matches:
        logger.info("No new tender matches to notify.")
        return 0, 0
        
    logger.info(f"Found {len(matches)} new tender matches to process.")
    dispatched_count = 0
    
    for match in matches:
        # Проверяем, не забракован ли тендер ИИ
        if match.ai_relevance is False:
            logger.info(
                f"Tender match {match.id} (tender_id={match.tender.id}) was rejected by AI. "
                "Marking as 'rejected_by_ai' and skipping notification."
            )
            match.status = MatchStatus.REJECTED_BY_AI
            continue

        # Проверяем, не истек ли дедлайн подачи заявок
        deadline_at = match.tender.deadline_at
        if not deadline_at and match.tender.raw_data:
            from worker.ingest import parse_deadline_string
            deadline_at = parse_deadline_string(match.tender.raw_data.get("deadline"))
            if deadline_at:
                match.tender.deadline_at = deadline_at
                session.add(match.tender)  # Явно помечаем для сохранения

        if deadline_at and deadline_at < datetime.now(timezone.utc):
            logger.info(
                f"Tender match {match.id} (tender_id={match.tender.id}) has expired deadline "
                f"({deadline_at}). Marking as expired and skipping notification."
            )
            match.status = MatchStatus.EXPIRED
            continue
        # Находим активные каналы уведомлений для профиля этого совпадения
        channels_stmt = (
            select(NotificationChannel)
            .where(
                NotificationChannel.profile_id == match.profile_id,
                NotificationChannel.is_active == True,
            )
        )
        channels = list(session.execute(channels_stmt).scalars())
        
        if not channels:
            logger.warning(
                f"No active notification channels found for profile: {match.profile.name} (id={match.profile_id}). "
                f"Skipping match (id={match.id})."
            )
            match.status = MatchStatus.PROCESSED
            continue
            
        for channel in channels:
            log = NotificationLog(
                match_id=match.id,
                channel_id=channel.id,
                status=NotificationStatus.PENDING,
                created_at=datetime.now(timezone.utc),
            )
            session.add(log)
            session.flush()  # Получаем ID лога
            
            if channel.type == "telegram":
                if not bot_token or bot_token == "your-bot-token":
                    error_msg = "TELEGRAM_BOT_TOKEN is not configured or set to default value."
                    logger.error(error_msg)
                    log.status = NotificationStatus.ERROR
                    log.error_message = error_msg
                    continue
                    
                chat_id = channel.config.get("chat_id")
                if not chat_id or chat_id == "your-chat-id":
                    error_msg = "chat_id is not configured in NotificationChannel config."
                    logger.error(error_msg)
                    log.status = NotificationStatus.ERROR
                    log.error_message = error_msg
                    continue
                    
                try:
                    text = format_tender_message(match)
                    reply_markup = {
                        "inline_keyboard": [
                            [
                                {"text": "🔎 Подробнее", "callback_data": f"detail:{match.id}"},
                                {"text": "✅ Принять", "callback_data": f"accept:{match.id}"},
                                {"text": "❌ Отклонить", "callback_data": f"reject:{match.id}"}
                            ]
                        ]
                    }
                    send_telegram_message(bot_token, str(chat_id), text, reply_markup)
                    log.status = NotificationStatus.SENT
                    log.sent_at = datetime.now(timezone.utc)
                    logger.info(f"Notification log (id={log.id}) sent successfully.")
                except Exception as e:
                    error_msg = str(e)
                    logger.exception(f"Error sending Telegram notification for log {log.id}")
                    log.status = NotificationStatus.ERROR
                    log.error_message = error_msg
                
                time.sleep(3.0)  # prevent hitting Telegram rate limits (429)
            else:
                error_msg = f"Unsupported notification channel type: {channel.type}"
                logger.error(error_msg)
                log.status = NotificationStatus.ERROR
                log.error_message = error_msg

        match.status = MatchStatus.PROCESSED
        dispatched_count += 1
        
    session.commit()
    logger.info(f"Dispatched notifications for {dispatched_count} matches.")
    return len(matches), dispatched_count


def dispatch_notifications(
    session: Session,
    tenant_id: int | None = None,
    *,
    drain: bool = False,
) -> int:
    """Dispatch one bounded batch, or drain all currently eligible batches.

    The default preserves the existing CLI/API single-batch behavior. Worker
    jobs use ``drain=True`` and release ORM objects between batches.
    """
    selected_count, dispatched_count = _dispatch_notification_batch(
        session,
        tenant_id,
    )
    if not drain:
        return dispatched_count

    total_dispatched = dispatched_count
    while selected_count:
        session.expunge_all()
        selected_count, batch_dispatched = _dispatch_notification_batch(
            session,
            tenant_id,
        )
        total_dispatched += batch_dispatched
    return total_dispatched
