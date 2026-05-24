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

def get_metadata_system_prompt(niche_description: str, keywords: list[str], negative_keywords: list[str]) -> str:
    keywords_str = ", ".join(keywords)
    neg_keywords_str = ", ".join(negative_keywords) if negative_keywords else "Нет"
    return f"""Ты — эксперт по анализу государственных закупок. Твоя задача — провести первичную экспресс-оценку релевантности тендера по его метаданным (название, заказчик, описание).

Мы занимаемся следующей деятельностью (наша ниша):
{niche_description}

Ключевые слова, которые нас интересуют: {keywords_str}
Исключения (минус-слова), которые нам КАТЕГОРИЧЕСКИ НЕ ПОДХОДЯТ: {neg_keywords_str}

Правила оценки:
1. Если из названия, заказчика или описания ОДНОЗНАЧНО понятно, что тендер относится к неподходящим или содержит минус-слова в нерелевантном контексте, верни "relevant": false.
2. Если тендер относится к нашей нише или информации в названии/описании недостаточно для однозначного отсечения, верни "relevant": true (чтобы мы скачали документы и проверили их на втором этапе глубокого анализа).

Ты ДОЛЖЕН вернуть JSON-объект (JSON Mode включен) со следующей структурой:
{{
  "relevant": true/false,
  "explanation": "Краткое объяснение на русском языке, почему тендер подходит или почему он отклонен (укажи конкретную причину)"
}}
"""

def get_deep_analysis_system_prompt(niche_description: str, keywords: list[str], negative_keywords: list[str]) -> str:
    keywords_str = ", ".join(keywords)
    neg_keywords_str = ", ".join(negative_keywords) if negative_keywords else "Нет"
    return f"""You are an expert assistant analyzing public procurement tenders.
Your task is to determine whether the provided tender documents match a search profile.

Our business niche description:
{niche_description}

Keywords of interest: {keywords_str}
Negative keywords to strictly exclude: {neg_keywords_str}

Rules:
1. Carefully read the provided document texts and determine if the core scope matches our business niche.
2. If the tender is about a general service or unrelated work, and our niche is not a prominent, specific component of the work, classify it as "relevant": false.
3. Check for negative keywords/exclusions and verify if they are present in a way that makes the tender irrelevant.

You MUST return a JSON object (JSON Mode is enabled) with the following structure:
{{
  "relevant": true/false,
  "explanation": "Краткое объяснение на русском языке, почему тендер подходит или нет",
  "commercial_proposal_info": {{
    "scope": "Краткое описание объема работ/поставки, количество оборудования, марки, технические требования (на русском)",
    "requirements": "Требования к участникам (опыт, СРО, лицензии, сертификаты, аттестаты) (на русском)",
    "budget_notes": "Сведения о бюджете, авансе, условиях оплаты и ценообразования из документов (на русском)",
    "suggested_actions": "Рекомендуемые действия для подготовки коммерческого предложения (на русском)"
  }}
}}
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
    niche_description: str,
    keywords: list[str],
    negative_keywords: list[str],
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

    metadata_system_prompt = get_metadata_system_prompt(niche_description, keywords, negative_keywords)

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": metadata_system_prompt},
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
    niche_description: str,
    keywords: list[str],
    negative_keywords: list[str],
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

    deep_analysis_system_prompt = get_deep_analysis_system_prompt(niche_description, keywords, negative_keywords)

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": deep_analysis_system_prompt},
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
