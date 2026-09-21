from __future__ import annotations

from typing import Any

from worker.analyzer.ai_providers import analyze_json, is_ai_provider_configured


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


def analyze_relevance_by_metadata(
    title: str,
    customer: str,
    niche_description: str,
    keywords: list[str],
    negative_keywords: list[str],
    description: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any] | None:
    desc_text = f"\nDescription: {description}" if description else ""
    return analyze_json(
        [
            {"role": "system", "content": get_metadata_system_prompt(niche_description, keywords, negative_keywords)},
            {"role": "user", "content": f"Tender Title: {title}\nCustomer: {customer}{desc_text}"},
        ],
        timeout=60,
        api_key=api_key,
    )


def analyze_tender_relevance(
    title: str,
    customer: str,
    documents_text: str,
    niche_description: str,
    keywords: list[str],
    negative_keywords: list[str],
    api_key: str | None = None,
) -> dict[str, Any] | None:
    max_chars = 30_000
    if len(documents_text) > max_chars:
        documents_text = documents_text[:max_chars] + "\n[Text truncated due to length limits]"
    return analyze_json(
        [
            {"role": "system", "content": get_deep_analysis_system_prompt(niche_description, keywords, negative_keywords)},
            {"role": "user", "content": f"Tender Title: {title}\nCustomer: {customer}\n\nDocument Text:\n{documents_text}"},
        ],
        timeout=60,
        api_key=api_key,
    )
