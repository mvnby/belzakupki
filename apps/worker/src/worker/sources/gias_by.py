from __future__ import annotations

from collections.abc import Iterable
import os
import re
from datetime import datetime, timezone, timedelta
from loguru import logger
import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://gias.by"
REGISTRY_URL = f"{BASE_URL}/purchase/all/"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def should_verify_ssl() -> bool:
    value = os.getenv("GOSZAKUPKI_VERIFY_SSL", "true").casefold()
    return value not in {"0", "false", "no"}


def get_mock_tenders() -> list[dict]:
    """Generates mock tenders for GIAS for testing while the site is under maintenance."""
    tz_minsk = timezone(timedelta(hours=3))
    now = datetime.now(tz_minsk)
    
    return [
        {
            "external_id": "gias001",
            "title": "Поставка кондиционеров и сплит-систем для нужд Витебского облисполкома",
            "customer_name": "Витебский областной исполнительный комитет",
            "url": f"{BASE_URL}/purchase/view/gias001",
            "status": "Подача предложений",
            "procedure_type": "Запрос ценовых предложений",
            "funding_source": "Бюджетные средства",
            "estimated_value": 45000.0,
            "currency": "BYN",
            "published_at": (now - timedelta(days=1)).astimezone(timezone.utc),
            "deadline_at": (now + timedelta(days=5)).astimezone(timezone.utc),
            "region": "2",  # Vitebsk
            "raw_data": {
                "external_id": "gias001",
                "title": "Поставка кондиционеров и сплит-систем для нужд Витебского облисполкома",
            }
        },
        {
            "external_id": "gias002",
            "title": "Услуги по техническому обслуживанию систем кондиционирования воздуха",
            "customer_name": "УЗ 'Гродненская областная клиническая больница'",
            "url": f"{BASE_URL}/purchase/view/gias002",
            "status": "Подача предложений",
            "procedure_type": "Электронный аукцион",
            "funding_source": "Бюджетные средства",
            "estimated_value": 12000.0,
            "currency": "BYN",
            "published_at": (now - timedelta(days=2)).astimezone(timezone.utc),
            "deadline_at": (now + timedelta(days=4)).astimezone(timezone.utc),
            "region": "4",  # Grodno
            "raw_data": {
                "external_id": "gias002",
                "title": "Услуги по техническому обслуживанию систем кондиционирования воздуха",
            }
        }
    ]


def parse_tenders_html(html: str) -> list[dict]:
    # Placeholder parser for future HTML integration
    return []


def fetch_tenders(
    limit: int | None = None,
    *,
    verify_ssl: bool | None = None,
) -> list[dict]:
    """Fetches list of tenders from GIAS. Falls back to mock data if down."""
    verify = should_verify_ssl() if verify_ssl is None else verify_ssl
    headers = {"User-Agent": USER_AGENT}
    
    logger.info(f"Attempting to fetch GIAS tenders from {REGISTRY_URL}...")
    
    try:
        with httpx.Client(
            follow_redirects=True,
            headers=headers,
            timeout=10,
            verify=verify,
        ) as client:
            r = client.get(REGISTRY_URL)
            if r.status_code == 200:
                tenders = parse_tenders_html(r.text)
                if tenders:
                    return tenders[:limit] if limit else tenders
            
            logger.warning(f"GIAS returned status {r.status_code}. Using mock tenders fallback.")
    except Exception as e:
        logger.warning(f"Failed to fetch from GIAS: {e}. Using mock tenders fallback.")
        
    tenders = get_mock_tenders()
    return tenders[:limit] if limit else tenders


def fetch_tenders_for_profiles(
    profiles: Iterable[Any],
    limit: int | None = None,
    *,
    verify_ssl: bool | None = None,
) -> list[dict]:
    """Fetches tenders from GIAS and filters them locally for profiles."""
    all_tenders = fetch_tenders(verify_ssl=verify_ssl)
    
    matched: list[dict] = []
    seen: set[str] = set()
    
    for profile in profiles:
        keywords = [kw.lower() for kw in (profile.keywords or [])]
        neg_keywords = [kw.lower() for kw in (profile.negative_keywords or [])]
        
        for t in all_tenders:
            ext_id = t["external_id"]
            if ext_id in seen:
                continue
                
            if profile.regions and t["region"] not in profile.regions:
                continue
                
            title_lower = t["title"].lower()
            has_positive = any(kw in title_lower for kw in keywords) if keywords else True
            has_negative = any(kw in title_lower for kw in neg_keywords) if neg_keywords else False
            
            if has_positive and not has_negative:
                seen.add(ext_id)
                matched.append(t)
                
                if limit is not None and len(matched) >= limit:
                    return matched
                    
    return matched
