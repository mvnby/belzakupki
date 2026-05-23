from __future__ import annotations

import json
import os
from typing import Any
import httpx
from loguru import logger

try:
    from tenacity import (
        retry,
        retry_if_exception_type,
        stop_after_attempt,
        wait_exponential,
    )
    _TENACITY_AVAILABLE = True
except ImportError:
    _TENACITY_AVAILABLE = False
    logger.warning(
        "tenacity is not installed — DeepSeek API calls will NOT be retried on failure. "
        "Run `pip install tenacity` to enable automatic retries."
    )

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

METADATA_SYSTEM_PROMPT = """Ты — эксперт по анализу государственных закупок. Твоя задача — провести первичную экспресс-оценку релевантности тендера по его метаданным (название, заказчик, описание).

Мы занимаемся ТОЛЬКО системами отопления, вентиляции и кондиционирования воздуха (HVAC) для зданий, помещений, офисов, промышленных объектов (поставка, монтаж, обслуживание, ремонт бытовых, полупромышленных и промышленных сплит-систем, мульти-сплит, VRF/VRV систем, приточно-вытяжной вентиляции и т.д.).

КАТЕГОРИЧЕСКИ НЕПОДХОДЯЩИЕ тендеры:
1. Кондиционирование транспорта: кондиционеры для тракторов, комбайнов, автобусов, поездов, вагонов метро, легковых и грузовых автомобилей, спецтехники.
2. Охлаждение шкафов автоматики, телекоммуникационных или серверных стоек (если это не кондиционирование самого помещения серверной).
3. Тендеры, не связанные с климатическим оборудованием (бытовая техника, общестроительные работы без вентиляции/кондиционирования).

Правила оценки:
- Если из названия, заказчика или описания ОДНОЗНАЧНО понятно, что тендер относится к неподходящим (например, "кондиционер для трактора", "автокондиционеры", "ремонт кондиционера тепловоза"), верни "relevant": false.
- Если тендер относится к нашей теме (HVAC зданий) или информации в названии/описании недостаточно для однозначного отсечения (например, просто "поставка кондиционеров", "оказание услуг по ремонту кондиционеров"), верни "relevant": true (чтобы мы скачали документы и проверили их на втором этапе).

Ты ДОЛЖЕН вернуть JSON-объект (JSON Mode включен) со следующей структурой:
{
  "relevant": true/false,
  "explanation": "Краткое объяснение на русском языке, почему тендер подходит или почему он отклонен (укажи конкретную причину)"
}
"""

SYSTEM_PROMPT = """You are an expert assistant analyzing public procurement tenders.
Your task is to determine whether the provided tender documents match a search profile for HVAC (Heating, Ventilation, and Air Conditioning / кондиционирование, вентиляция, отопление).
Specifically, we look for:
- Supply, installation, maintenance, or repair of air conditioners, split systems, multi-split systems, VRF/VRV systems.
- Design, installation, or maintenance of ventilation systems.
- Do NOT classify general building renovation/repairs as relevant unless air conditioning/ventilation is a prominent, specific component of the work.
- Exclude automotive or agricultural vehicle AC systems unless specifically requested (we exclude car/tractor AC by default).

You MUST return a JSON object (JSON Mode is enabled) with the following structure:
{
  "relevant": true/false,
  "explanation": "Краткое объяснение на русском языке, почему тендер подходит или нет",
  "commercial_proposal_info": {
    "scope": "Краткое описание объема работ/поставки, количество кондиционеров, марки, технические требования (на русском)",
    "requirements": "Требования к участникам (опыт, СРО, лицензии, сертификаты) (на русском)",
    "budget_notes": "Сведения о бюджете, авансе, условиях оплаты и ценообразования из документов (на русском)",
    "suggested_actions": "Рекомендуемые действия для подготовки коммерческого предложения (на русском)"
  }
}
"""

def _do_deepseek_post(url: str, payload: dict, headers: dict, timeout: int) -> dict:
    """Raw HTTP call to DeepSeek — separated so tenacity can wrap it."""
    response = httpx.post(url, json=payload, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


if _TENACITY_AVAILABLE:
    _do_deepseek_post = retry(
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.RequestError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        reraise=True,
    )(_do_deepseek_post)


def analyze_relevance_by_metadata(
    title: str,
    customer: str,
    description: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any] | None:
    token = api_key or os.getenv("DEEPSEEK_TOKEN")
    if not token or token == "your-deepseek-token":
        logger.warning("DEEPSEEK_TOKEN is not configured. Skipping AI metadata analysis.")
        return None

    desc_text = f"\nDescription: {description}" if description else ""
    user_content = f"Tender Title: {title}\nCustomer: {customer}{desc_text}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": METADATA_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }

    try:
        logger.info(f"Sending metadata of tender '{title}' to DeepSeek API for Stage 1 check...")
        result = _do_deepseek_post(DEEPSEEK_API_URL, payload, headers, timeout=30)
        content = result["choices"][0]["message"]["content"]
        analysis = json.loads(content)
        logger.info(f"DeepSeek metadata analysis complete. Relevant: {analysis.get('relevant')}")
        return analysis

    except Exception as e:
        logger.error(f"DeepSeek metadata API call failed: {e}")
        return None

def analyze_tender_relevance(
    title: str,
    customer: str,
    documents_text: str,
    api_key: str | None = None,
) -> dict[str, Any] | None:
    token = api_key or os.getenv("DEEPSEEK_TOKEN")
    if not token or token == "your-deepseek-token":
        logger.warning("DEEPSEEK_TOKEN is not configured. Skipping AI analysis.")
        return None

    # Truncate document text to prevent exceeding context window (e.g. max 30,000 characters)
    max_chars = 30000
    if len(documents_text) > max_chars:
        logger.info(f"Tender text length ({len(documents_text)}) exceeds limit. Truncating to {max_chars} chars.")
        documents_text = documents_text[:max_chars] + "\n[Text truncated due to length limits]"

    user_content = f"Tender Title: {title}\nCustomer: {customer}\n\nDocument Text:\n{documents_text}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }

    try:
        logger.info(f"Sending tender '{title}' to DeepSeek API...")
        result = _do_deepseek_post(DEEPSEEK_API_URL, payload, headers, timeout=45)
        content = result["choices"][0]["message"]["content"]
        analysis = json.loads(content)
        logger.info(f"DeepSeek analysis complete. Relevant: {analysis.get('relevant')}")
        return analysis

    except Exception as e:
        logger.error(f"DeepSeek API call failed: {e}")
        return None
