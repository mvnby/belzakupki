from __future__ import annotations

from datetime import datetime, timezone, timedelta
import html
import os
import time
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload

from belzakupki_db.models import NotificationChannel, NotificationLog, TenderMatch, Tender, SearchProfile
from belzakupki_db.enums import MatchStatus, NotificationStatus
from worker.resource_limits import positive_int_env


NOTIFICATION_BATCH_SIZE = positive_int_env("WORKER_NOTIFICATION_BATCH_SIZE", 50)
NOTIFICATION_MAX_ATTEMPTS = positive_int_env("WORKER_NOTIFICATION_MAX_ATTEMPTS", 5)
NOTIFICATION_RETRY_SECONDS = positive_int_env("WORKER_NOTIFICATION_RETRY_SECONDS", 60)


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
    if response.json().get("ok") is not True:
        raise RuntimeError("Telegram did not confirm notification delivery")


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


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _deliver_match(session: Session, match: TenderMatch, bot_token: str | None) -> int:
    deadline = match.tender.deadline_at
    if not deadline and match.tender.raw_data:
        from worker.ingest import parse_deadline_string
        deadline = parse_deadline_string(match.tender.raw_data.get("deadline"))
        if deadline:
            match.tender.deadline_at = deadline
    if deadline and _as_utc(deadline) < datetime.now(timezone.utc):
        match.status = MatchStatus.EXPIRED
        return 0

    channels = list(session.scalars(select(NotificationChannel).where(
        NotificationChannel.profile_id == match.profile_id,
        NotificationChannel.is_active.is_(True),
    ).order_by(NotificationChannel.id)))
    if not channels:
        match.status = MatchStatus.PROCESSED
        return 0

    all_sent = True
    for channel in channels:
        log = session.scalar(select(NotificationLog).where(
            NotificationLog.match_id == match.id,
            NotificationLog.channel_id == channel.id,
        ))
        if log is not None and log.status == NotificationStatus.SENT:
            continue
        now = datetime.now(timezone.utc)
        if log is not None and (
            log.attempt_count >= NOTIFICATION_MAX_ATTEMPTS
            or (log.next_attempt_at and _as_utc(log.next_attempt_at) > now)
        ):
            all_sent = False
            continue
        if log is None:
            log = NotificationLog(match_id=match.id, channel_id=channel.id,
                                  attempt_count=0)
            session.add(log)
        log.attempt_count += 1
        log.status = NotificationStatus.PENDING
        log.error_message = None
        log.next_attempt_at = None
        session.flush()
        try:
            if channel.type != "telegram":
                raise ValueError(f"Unsupported notification channel type: {channel.type}")
            if not bot_token or bot_token == "your-bot-token":
                raise ValueError("TELEGRAM_BOT_TOKEN is not configured")
            chat_id = (channel.config or {}).get("chat_id")
            if not chat_id or chat_id == "your-chat-id":
                raise ValueError("Notification channel chat_id is not configured")
            text = format_tender_message(match)
            reply_markup = {"inline_keyboard": [[
                {"text": "🔎 Подробнее", "callback_data": f"detail:{match.id}"},
                {"text": "✅ Принять", "callback_data": f"accept:{match.id}"},
                {"text": "❌ Отклонить", "callback_data": f"reject:{match.id}"},
            ]]}
            try:
                send_telegram_message(bot_token, str(chat_id), text, reply_markup)
            finally:
                time.sleep(3.0)
        except Exception as error:
            all_sent = False
            log.status = NotificationStatus.ERROR
            message = str(error)
            log.error_message = message.replace(bot_token, "<redacted>") if bot_token else message
            if log.attempt_count < NOTIFICATION_MAX_ATTEMPTS:
                delay = min(NOTIFICATION_RETRY_SECONDS * 2 ** min(log.attempt_count - 1, 10), 3600)
                log.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            logger.warning("Notification {} failed (attempt {}/{}): {}",
                           log.id, log.attempt_count, NOTIFICATION_MAX_ATTEMPTS,
                           log.error_message)
        else:
            log.status = NotificationStatus.SENT
            log.sent_at = datetime.now(timezone.utc)

    if all_sent:
        match.status = MatchStatus.PROCESSED
        return 1
    return 0


def _dispatch_notification_batch(
    session: Session,
    tenant_id: int | None = None,
    *,
    due_at: datetime | None = None,
    through_id: int | None = None,
) -> tuple[int, int]:
    if os.getenv("WORKER_NOTIFICATIONS_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        return 0, 0
    due_at = due_at or datetime.now(timezone.utc)
    active_channels = select(NotificationChannel.id).where(
        NotificationChannel.profile_id == TenderMatch.profile_id,
        NotificationChannel.is_active.is_(True),
    )
    channel_logs = active_channels.outerjoin(NotificationLog, and_(
        NotificationLog.channel_id == NotificationChannel.id,
        NotificationLog.match_id == TenderMatch.id,
    ))
    unfinished_channels = channel_logs.where(or_(
        NotificationLog.id.is_(None), NotificationLog.status != NotificationStatus.SENT,
    ))
    due_channels = channel_logs.where(or_(
        NotificationLog.id.is_(None),
        and_(NotificationLog.status != NotificationStatus.SENT,
             NotificationLog.attempt_count < NOTIFICATION_MAX_ATTEMPTS,
             or_(NotificationLog.next_attempt_at.is_(None),
                 NotificationLog.next_attempt_at <= due_at)),
    ))
    stmt = (
        select(TenderMatch)
        .options(joinedload(TenderMatch.tender).joinedload(Tender.source),
                 joinedload(TenderMatch.profile))
        .where(TenderMatch.status == MatchStatus.NEW,
               TenderMatch.ai_relevance.is_(True),
               or_(~unfinished_channels.exists(), due_channels.exists()))
        .order_by(TenderMatch.id)
        .limit(NOTIFICATION_BATCH_SIZE)
        .with_for_update(of=TenderMatch, skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if tenant_id is not None:
        stmt = stmt.join(TenderMatch.profile).where(SearchProfile.tenant_id == tenant_id)
    if through_id is not None:
        stmt = stmt.where(TenderMatch.id <= through_id)
    match_ids = [match.id for match in session.execute(stmt).scalars()]
    dispatched = 0
    for match_id in match_ids:
        # The preceding match commits its own delivery results. Reacquire this
        # row and recheck eligibility after that commit released the batch locks.
        match = session.execute(stmt.where(TenderMatch.id == match_id)).scalar_one_or_none()
        if match is None:
            continue
        try:
            dispatched += _deliver_match(session, match, os.getenv("TELEGRAM_BOT_TOKEN"))
            session.commit()
        except Exception:
            session.rollback()
            raise
    return len(match_ids), dispatched


def dispatch_notifications(
    session: Session,
    tenant_id: int | None = None,
    *,
    drain: bool = False,
) -> int:
    """Visit each due delivery in a fixed snapshot, in bounded batches.

    Errors schedule a later attempt; sent channels are never selected again.
    A fixed due time prevents a long drain from retrying its own failures.
    PostgreSQL match locks prevent simultaneous sends by competing workers.
    """
    if os.getenv("WORKER_NOTIFICATIONS_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        return 0
    due_at = datetime.now(timezone.utc)
    through_id = session.scalar(select(func.max(TenderMatch.id))) if drain else None
    selected_count, dispatched_count = _dispatch_notification_batch(
        session, tenant_id, due_at=due_at, through_id=through_id,
    )
    if not drain:
        return dispatched_count
    total_dispatched = dispatched_count
    while selected_count:
        session.expunge_all()
        selected_count, batch_dispatched = _dispatch_notification_batch(
            session, tenant_id, due_at=due_at, through_id=through_id,
        )
        total_dispatched += batch_dispatched
    return total_dispatched
