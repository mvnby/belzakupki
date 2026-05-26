import httpx
import logging
import re
from typing import Dict, Any, Optional

logger = logging.getLogger("belzakupki.crm_service")

def extract_numeric_price(val_str: Any) -> Optional[float]:
    if val_str is None:
        return None
    if isinstance(val_str, (int, float)):
        return float(val_str)
    
    val_str = str(val_str)
    # Remove spaces and normalize decimal points
    cleaned = "".join(c for c in val_str if c.isdigit() or c in ".,")
    if not cleaned:
        return None
    if "," in cleaned:
        if "." in cleaned:
            cleaned = cleaned.replace(",", "")
        else:
            cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None

def format_bitrix24_comments(tender: Any, match: Any) -> str:
    est_val = tender.raw_data.get("estimated_value", "Не указана") if tender.raw_data else "Не указана"
    deadline = tender.deadline_at.strftime("%d.%m.%Y") if tender.deadline_at else "Не указан"
    
    comments = []
    comments.append(f"<p><b>Заказчик:</b> {tender.customer_name or 'Не указан'}</p>")
    comments.append(f"<p><b>Ссылка:</b> <a href=\"{tender.url}\" target=\"_blank\">{tender.url}</a></p>")
    comments.append(f"<p><b>Ориентировочная стоимость:</b> {est_val}</p>")
    comments.append(f"<p><b>Дедлайн подачи предложений:</b> {deadline}</p>")
    comments.append(f"<p><b>Балл соответствия профилю:</b> {match.score}%</p>")
    comments.append(f"<p><b>Совпавшие ключевые слова:</b> {', '.join(match.matched_keywords)}</p>")
    
    if match.ai_analysis:
        comments.append("<hr/>")
        comments.append("<h3>🤖 Экспертный анализ ИИ (DeepSeek):</h3>")
        
        relevance_exp = match.ai_analysis.get("relevance_explanation") or match.reason
        if relevance_exp:
            comments.append(f"<p><b>Оценка релевантности:</b><br/>{relevance_exp}</p>")
            
        key_points = match.ai_analysis.get("key_points")
        if key_points and isinstance(key_points, list):
            comments.append("<p><b>Ключевые моменты ТЗ:</b></p><ul>")
            for pt in key_points:
                comments.append(f"<li>{pt}</li>")
            comments.append("</ul>")
            
        risks = match.ai_analysis.get("risks")
        if risks and isinstance(risks, list):
            comments.append("<p><b>Выявленные риски:</b></p><ul>")
            for rk in risks:
                comments.append(f"<li>⚠️ {rk}</li>")
            comments.append("</ul>")
            
        cp_info = match.ai_analysis.get("commercial_proposal_info")
        if cp_info and isinstance(cp_info, dict):
            comments.append("<p><b>Инструкция для КП:</b></p>")
            scope = cp_info.get("scope")
            if scope:
                comments.append(f"<p><i>Объем поставки/работ:</i> {scope}</p>")
            reqs = cp_info.get("requirements")
            if reqs:
                comments.append(f"<p><i>Требования к поставщику:</i> {reqs}</p>")
            budget_notes = cp_info.get("budget_notes")
            if budget_notes:
                comments.append(f"<p><i>Бюджетные особенности:</i> {budget_notes}</p>")
                
    return "".join(comments)

def format_amocrm_notes(tender: Any, match: Any) -> str:
    est_val = tender.raw_data.get("estimated_value", "Не указана") if tender.raw_data else "Не указана"
    deadline = tender.deadline_at.strftime("%d.%m.%Y") if tender.deadline_at else "Не указан"
    
    notes = []
    notes.append(f"Заказчик: {tender.customer_name or 'Не указан'}")
    notes.append(f"Ссылка: {tender.url}")
    notes.append(f"Ориентировочная стоимость: {est_val}")
    notes.append(f"Дедлайн подачи предложений: {deadline}")
    notes.append(f"Балл соответствия профилю: {match.score}%")
    notes.append(f"Совпавшие ключевые слова: {', '.join(match.matched_keywords)}")
    
    if match.ai_analysis:
        notes.append("\n---")
        notes.append("🤖 Экспертный анализ ИИ (DeepSeek):")
        
        relevance_exp = match.ai_analysis.get("relevance_explanation") or match.reason
        if relevance_exp:
            notes.append(f"\nОценка релевантности:\n{relevance_exp}")
            
        key_points = match.ai_analysis.get("key_points")
        if key_points and isinstance(key_points, list):
            notes.append("\nКлючевые моменты ТЗ:")
            for pt in key_points:
                notes.append(f"- {pt}")
                
        risks = match.ai_analysis.get("risks")
        if risks and isinstance(risks, list):
            notes.append("\nВыявленные риски:")
            for rk in risks:
                notes.append(f"- ⚠️ {rk}")
                
        cp_info = match.ai_analysis.get("commercial_proposal_info")
        if cp_info and isinstance(cp_info, dict):
            notes.append("\nИнструкция для КП:")
            scope = cp_info.get("scope")
            if scope:
                notes.append(f"  Объем поставки/работ: {scope}")
            reqs = cp_info.get("requirements")
            if reqs:
                notes.append(f"  Требования к поставщику: {reqs}")
            budget_notes = cp_info.get("budget_notes")
            if budget_notes:
                notes.append(f"  Бюджетные особенности: {budget_notes}")
                
    return "\n".join(notes)

async def export_to_bitrix24(webhook_url: str, tender: Any, match: Any) -> str:
    """Экспорт сделки в Битрикс24 через входящий вебхук."""
    endpoint = webhook_url.rstrip("/") + "/crm.deal.add"
    
    # Extract price
    est_raw = tender.raw_data.get("estimated_value") if tender.raw_data else None
    price = extract_numeric_price(est_raw)
    
    comments_html = format_bitrix24_comments(tender, match)
    
    payload = {
        "fields": {
            "TITLE": f"Закупка: {tender.title}",
            "OPPORTUNITY": price if price is not None else 0.0,
            "CURRENCY_ID": "BYN",
            "COMMENTS": comments_html,
        }
    }
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            res_data = response.json()
            if "result" in res_data:
                deal_id = str(res_data["result"])
                logger.info(f"Successfully exported deal to Bitrix24. ID: {deal_id}")
                return deal_id
            else:
                error_msg = res_data.get("error_description", "Unknown error")
                raise Exception(f"Bitrix24 API error: {error_msg}")
        except Exception as e:
            logger.error(f"Failed to export to Bitrix24: {e}")
            raise Exception(f"Ошибка при отправке в Битрикс24: {str(e)}")

async def export_to_amocrm(subdomain: str, token: str, tender: Any, match: Any) -> str:
    """Экспорт лида в amoCRM через REST API v4."""
    base_url = f"https://{subdomain}.amocrm.ru"
    leads_endpoint = f"{base_url}/api/v4/leads"
    
    # Extract price
    est_raw = tender.raw_data.get("estimated_value") if tender.raw_data else None
    price = extract_numeric_price(est_raw)
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # 1. Create Lead
    lead_payload = [
        {
            "name": f"Закупка: {tender.title[:200]}",
            "price": int(price) if price is not None else 0,
        }
    ]
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            # Create the lead
            response = await client.post(leads_endpoint, json=lead_payload, headers=headers)
            response.raise_for_status()
            res_data = response.json()
            
            # Extract lead ID
            leads = res_data.get("_embedded", {}).get("leads", [])
            if not leads:
                raise Exception("amoCRM did not return the created lead ID in _embedded.leads")
            
            lead_id = str(leads[0]["id"])
            logger.info(f"Successfully created amoCRM Lead. ID: {lead_id}")
            
            # 2. Add Common Note with details
            notes_endpoint = f"{base_url}/api/v4/leads/{lead_id}/notes"
            note_payload = [
                {
                    "note_type": "common",
                    "params": {
                        "text": format_amocrm_notes(tender, match)
                    }
                }
            ]
            
            note_response = await client.post(notes_endpoint, json=note_payload, headers=headers)
            if note_response.status_code not in (200, 201):
                logger.warning(f"amoCRM lead created (ID: {lead_id}), but failed to attach note: {note_response.text}")
            
            return lead_id
            
        except Exception as e:
            logger.error(f"Failed to export to amoCRM: {e}")
            raise Exception(f"Ошибка при отправке в amoCRM: {str(e)}")
