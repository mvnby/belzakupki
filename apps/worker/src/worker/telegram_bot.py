from __future__ import annotations

import os
import time
import traceback
import httpx
from loguru import logger
from sqlalchemy.orm import joinedload

from belzakupki_db.session import SessionLocal
from belzakupki_db.models import TenderMatch, Tender
from belzakupki_db.enums import MatchStatus
from worker.notifications import format_tender_message, send_telegram_message

def answer_callback_query(bot_token: str, callback_query_id: str, text: str | None = None) -> None:
    """Отправляет ответ на callback query в Telegram, чтобы у пользователя исчез индикатор загрузки на кнопке.

    Может опционально показывать всплывающее уведомление (toast).
    """
    url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"
    payload = {
        "callback_query_id": callback_query_id,
    }
    if text:
        payload["text"] = text
    try:
        response = httpx.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            logger.error(f"Failed to answer callback query: {response.text}")
    except Exception as e:
        logger.error(f"Error answering callback query: {e}")

def edit_message_text(bot_token: str, chat_id: str, message_id: int, text: str, reply_markup: dict | None = None) -> None:
    """Изменяет текст и инлайн-клавиатуру уже отправленного сообщения в Telegram."""
    url = f"https://api.telegram.org/bot{bot_token}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    try:
        response = httpx.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            logger.error(f"Failed to edit message text: {response.text}")
    except Exception as e:
        logger.error(f"Error editing message text: {e}")

def handle_callback_query(bot_token: str, callback_query: dict) -> None:
    """Обрабатывает нажатия на инлайн-кнопки под карточкой тендера в Telegram.

    Поддерживает действия:
    - detail: Отправить полное обоснование и ТЗ ИИ новым сообщением.
    - accept: Перевести статус совпадения в 'accepted', убрать кнопки, добавить пометку об одобрении.
    - reject: Перевести статус совпадения в 'rejected', убрать кнопки, добавить пометку об отклонении.
    """
    callback_query_id = callback_query["id"]
    data = callback_query.get("data", "")
    message = callback_query.get("message")
    
    if not message or not data:
        answer_callback_query(bot_token, callback_query_id)
        return
        
    chat_id = str(message["chat"]["id"])
    message_id = message["message_id"]
    
    try:
        action, match_id_str = data.split(":", 1)
        match_id = int(match_id_str)
    except ValueError:
        logger.error(f"Invalid callback data format: {data}")
        answer_callback_query(bot_token, callback_query_id, "Ошибка формата данных")
        return

    session = SessionLocal()
    try:
        # Load match with relationships
        match = session.query(TenderMatch).options(
            joinedload(TenderMatch.tender).joinedload(Tender.source),
            joinedload(TenderMatch.profile),
        ).filter(TenderMatch.id == match_id).one_or_none()
        
        if not match:
            logger.error(f"Match ID {match_id} not found in database.")
            answer_callback_query(bot_token, callback_query_id, "Тендер не найден в базе")
            return
            
        if action == "detail":
            # Send detailed AI analysis as a new message
            logger.info(f"User requested details for match ID {match_id}")
            ai_analysis = match.ai_analysis or {}
            info = ai_analysis.get("commercial_proposal_info", {})
            
            scope = info.get("scope") or "Не указан"
            reqs = info.get("requirements") or "Не указаны"
            budget = info.get("budget_notes") or "Не указан"
            actions = info.get("suggested_actions") or "Не указаны"
            explanation = ai_analysis.get("explanation") or "Нет описания"
            
            detail_text = (
                f"📋 <b>Детальный анализ тендера #{match_id}</b>\n"
                f"<i>{match.tender.title}</i>\n\n"
                f"🧠 <b>Обоснование ИИ:</b>\n{explanation}\n\n"
                f"📝 <b>Объем работ:</b>\n{scope}\n\n"
                f"🛡️ <b>Требования:</b>\n{reqs}\n\n"
                f"💵 <b>Оплата и бюджет:</b>\n{budget}\n\n"
                f"⚡ <b>Рекомендуемые действия:</b>\n{actions}"
            )
            
            send_telegram_message(bot_token, chat_id, detail_text)
            answer_callback_query(bot_token, callback_query_id, "Анализ отправлен")
            
        elif action == "accept":
            logger.info(f"User accepted match ID {match_id}")
            match.status = MatchStatus.ACCEPTED
            session.add(match)
            session.commit()
            
            # Edit original message to remove buttons and append acceptance text
            orig_text = format_tender_message(match)
            updated_text = orig_text + "\n\n<b>✅ Принят в работу</b>"
            edit_message_text(bot_token, chat_id, message_id, updated_text, reply_markup={"inline_keyboard": []})
            answer_callback_query(bot_token, callback_query_id, "Тендер принят в работу")
            
        elif action == "reject":
            logger.info(f"User rejected match ID {match_id}")
            match.status = MatchStatus.REJECTED
            session.add(match)
            session.commit()
            
            # Edit original message to remove buttons and append rejection text
            orig_text = format_tender_message(match)
            updated_text = orig_text + "\n\n<b>❌ Отклонен</b>"
            edit_message_text(bot_token, chat_id, message_id, updated_text, reply_markup={"inline_keyboard": []})
            answer_callback_query(bot_token, callback_query_id, "Тендер отклонен")
            
        else:
            logger.warning(f"Unknown action: {action}")
            answer_callback_query(bot_token, callback_query_id)
            
    except Exception as e:
        logger.exception(f"Error handling callback query: {e}")
        answer_callback_query(bot_token, callback_query_id, "Произошла внутренняя ошибка")
    finally:
        session.close()

def start_telegram_bot_listener() -> None:
    """Запускает бесконечный цикл long polling (getUpdates) для получения событий Telegram-бота.

    Слушает события типа callback_query для обработки нажатий на инлайн-кнопки.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token or bot_token == "your-bot-token":
        logger.warning("TELEGRAM_BOT_TOKEN is not set. Telegram bot updates listener will not start.")
        return
        
    logger.info("Starting Telegram bot updates listener (long polling)...")
    offset = 0
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    
    while True:
        try:
            payload = {
                "offset": offset,
                "timeout": 20,
                "allowed_updates": ["callback_query"]
            }
            # Use a longer timeout for long polling requests
            response = httpx.post(url, json=payload, timeout=25)
            
            if response.status_code != 200:
                logger.error(f"Telegram getUpdates failed with status {response.status_code}: {response.text}")
                time.sleep(10)
                continue
                
            updates = response.json().get("result", [])
            for update in updates:
                offset = update["update_id"] + 1
                
                if "callback_query" in update:
                    handle_callback_query(bot_token, update["callback_query"])
                    
        except httpx.RequestError as e:
            # Silent retry on connection timeouts/errors
            time.sleep(5)
        except Exception as e:
            logger.error(f"Unexpected error in Telegram bot listener loop: {e}\n{traceback.format_exc()}")
            time.sleep(10)
