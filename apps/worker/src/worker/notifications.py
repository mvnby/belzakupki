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

from belzakupki_db.models import NotificationChannel, NotificationLog, TenderMatch, Tender


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    
    logger.info(f"Sending Telegram notification to chat_id={chat_id}")
    
    response = httpx.post(url, json=payload, timeout=10)
    
    if response.status_code != 200:
        logger.error(f"Failed to send Telegram message: {response.text}")
        response.raise_for_status()


def format_tender_message(match: TenderMatch) -> str:
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


def dispatch_notifications(session: Session) -> int:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    
    # Находим все совпадения со статусом 'new'
    stmt = (
        select(TenderMatch)
        .options(
            joinedload(TenderMatch.tender).joinedload(Tender.source),
            joinedload(TenderMatch.profile),
        )
        .where(TenderMatch.status == "new")
        .order_by(TenderMatch.created_at.asc())
    )
    matches = list(session.execute(stmt).scalars())
    
    if not matches:
        logger.info("No new tender matches to notify.")
        return 0
        
    logger.info(f"Found {len(matches)} new tender matches to process.")
    dispatched_count = 0
    
    for match in matches:
        # Проверяем, не забракован ли тендер ИИ
        if match.ai_relevance is False:
            logger.info(
                f"Tender match {match.id} (tender_id={match.tender.id}) was rejected by AI. "
                "Marking as 'rejected_by_ai' and skipping notification."
            )
            match.status = "rejected_by_ai"
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
            match.status = "expired"
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
            match.status = "processed"
            continue
            
        for channel in channels:
            log = NotificationLog(
                match_id=match.id,
                channel_id=channel.id,
                status="pending",
                created_at=datetime.now(timezone.utc),
            )
            session.add(log)
            session.flush()  # Получаем ID лога
            
            if channel.type == "telegram":
                if not bot_token or bot_token == "your-bot-token":
                    error_msg = "TELEGRAM_BOT_TOKEN is not configured or set to default value."
                    logger.error(error_msg)
                    log.status = "error"
                    log.error_message = error_msg
                    continue
                    
                chat_id = channel.config.get("chat_id")
                if not chat_id or chat_id == "your-chat-id":
                    error_msg = "chat_id is not configured in NotificationChannel config."
                    logger.error(error_msg)
                    log.status = "error"
                    log.error_message = error_msg
                    continue
                    
                try:
                    text = format_tender_message(match)
                    send_telegram_message(bot_token, str(chat_id), text)
                    log.status = "sent"
                    log.sent_at = datetime.now(timezone.utc)
                    logger.info(f"Notification log (id={log.id}) sent successfully.")
                except Exception as e:
                    error_msg = str(e)
                    logger.exception(f"Error sending Telegram notification for log {log.id}")
                    log.status = "error"
                    log.error_message = error_msg
                
                time.sleep(3.0)  # prevent hitting Telegram rate limits (429)
            else:
                error_msg = f"Unsupported notification channel type: {channel.type}"
                logger.error(error_msg)
                log.status = "error"
                log.error_message = error_msg
                
        match.status = "processed"
        dispatched_count += 1
        
    session.commit()
    logger.info(f"Dispatched notifications for {dispatched_count} matches.")
    return dispatched_count
