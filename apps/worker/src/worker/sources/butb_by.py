from __future__ import annotations

from collections.abc import Iterable
import os
import re
from datetime import datetime, timezone, timedelta
from loguru import logger
import httpx
from bs4 import BeautifulSoup

from worker.sources.base import normalize_html_text

BASE_URL = "https://zakupki.butb.by"
REGISTRY_URL = f"{BASE_URL}/auctions/reestrauctions.html"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def should_verify_ssl() -> bool:
    value = os.getenv("GOSZAKUPKI_VERIFY_SSL", "true").casefold()
    return value not in {"0", "false", "no"}


def parse_date(date_str: str | None) -> datetime | None:
    """Parses DD.MM.YYYY string and converts to UTC timezone (Minsk UTC+3)."""
    if not date_str:
        return None
    match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", date_str)
    if not match:
        return None
    day, month, year = match.groups()
    try:
        tz_minsk = timezone(timedelta(hours=3))
        dt = datetime(int(year), int(month), int(day), 0, 0, tzinfo=tz_minsk)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def parse_price(price_str: str | None) -> tuple[float | None, str]:
    """Parses value and currency from string like '268 269,05 BYN'."""
    if not price_str:
        return None, "BYN"
    
    # Extract number and currency
    # Replace non-breaking spaces and other formatting
    clean_str = normalize_html_text(price_str).replace("\xa0", " ").replace(" ", "")
    
    # Match currency
    curr_match = re.search(r"(BYN|USD|EUR|RUB|byn|usd|eur|rub)", clean_str, re.IGNORECASE)
    currency = curr_match.group(1).upper() if curr_match else "BYN"
    
    # Match numeric part (digits, commas, periods)
    num_match = re.search(r"([\d\.,\s]+)", clean_str)
    if not num_match:
        return None, currency
        
    num_str = num_match.group(1).replace(",", ".")
    try:
        return float(num_str), currency
    except ValueError:
        return None, currency


def extract_region(customer_name: str | None) -> str | None:
    """Extracts canonical region code from customer name/text.
    
    '1' = Brest, '2' = Vitebsk, '3' = Gomel, '4' = Grodno,
    '5' = Minsk City, '6' = Minsk region, '7' = Mogilev
    """
    if not customer_name:
        return None
    
    text = customer_name.lower()
    
    if "брест" in text:
        return "1"
    if "витеб" in text:
        return "2"
    if "гоме" in text:
        return "3"
    if "гродн" in text:
        return "4"
    if "могил" in text or "могилев" in text or "могилёв" in text:
        return "7"
    if "минс" in text or "белфармация" in text or "белмедтехника" in text:
        if "област" in text or "областн" in text or "район" in text:
            return "6"
        return "5"
        
    return None


def parse_tenders_html(html: str) -> list[dict]:
    """Parses BUTB registry HTML and extracts tender items."""
    soup = BeautifulSoup(html, "html.parser")
    
    tenders = []
    
    # Search for rows containing class 'iceDatTblRow' or tr elements inside the main form table
    # JSF renders table rows dynamically, let's find the rows that have enough cells
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 8:
            continue
            
        # Try to find if first cell contains a registration number like PR202..., AU202...
        cell_0_text = normalize_html_text(cells[0].get_text(" ", strip=True))
        id_match = re.search(r"^([A-Z]{2}\d+)", cell_0_text)
        if not id_match:
            continue
            
        external_id = id_match.group(1)
        
        # Parse fields based on columns:
        # idx 0: Reg. No
        # idx 1: Name / Title
        # idx 2: Procedure type
        # idx 3: Published date
        # idx 4: Price / currency
        # idx 5: Customer
        # idx 6: Funding
        # idx 7: Submission deadline
        # idx 9: Status (often index 9 or last cells)
        
        title = normalize_html_text(cells[1].get_text(" ", strip=True))
        procedure_type = normalize_html_text(cells[2].get_text(" ", strip=True))
        published_str = normalize_html_text(cells[3].get_text(" ", strip=True))
        price_str = normalize_html_text(cells[4].get_text(" ", strip=True))
        customer = normalize_html_text(cells[5].get_text(" ", strip=True))
        funding = normalize_html_text(cells[6].get_text(" ", strip=True))
        deadline_str = normalize_html_text(cells[7].get_text(" ", strip=True))
        
        # Status is usually the second to last cell or index 9
        status = "posted"
        if len(cells) >= 10:
            status = normalize_html_text(cells[9].get_text(" ", strip=True))
        elif len(cells) >= 9:
            status = normalize_html_text(cells[8].get_text(" ", strip=True))
            
        # Parse price and dates
        val, curr = parse_price(price_str)
        published_dt = parse_date(published_str)
        deadline_dt = parse_date(deadline_str)
        region = extract_region(customer)
        
        tender_url = f"{BASE_URL}/auctions/viewinvitation.html?auction={external_id}"
        
        tenders.append({
            "external_id": external_id,
            "title": title,
            "customer_name": customer,
            "url": tender_url,
            "status": status,
            "procedure_type": procedure_type,
            "funding_source": funding,
            "estimated_value": val,
            "currency": curr,
            "published_at": published_dt,
            "deadline_at": deadline_dt,
            "region": region,
            "raw_data": {
                "external_id": external_id,
                "title": title,
                "procedure_type": procedure_type,
                "published_str": published_str,
                "price_str": price_str,
                "customer_name": customer,
                "funding_source": funding,
                "deadline_str": deadline_str,
                "status": status,
            }
        })
        
    return tenders


def fetch_tenders(
    limit: int | None = None,
    *,
    verify_ssl: bool | None = None,
) -> list[dict]:
    """Fetches list of tenders from the BUTB ETP registry."""
    verify = should_verify_ssl() if verify_ssl is None else verify_ssl
    headers = {"User-Agent": USER_AGENT}
    
    logger.info(f"Fetching BUTB tenders from {REGISTRY_URL}...")
    
    with httpx.Client(
        follow_redirects=True,
        headers=headers,
        timeout=20,
        verify=verify,
    ) as client:
        # Establish session cookies by hitting the main index first
        client.get(f"{BASE_URL}/").raise_for_status()
        
        # Load registry page
        r = client.get(REGISTRY_URL)
        r.raise_for_status()
        
        tenders = parse_tenders_html(r.text)
        logger.info(f"Successfully fetched {len(tenders)} tenders from BUTB.")
        
        if limit is not None:
            tenders = tenders[:limit]
            
        return tenders


def fetch_tenders_for_profiles(
    profiles: Iterable[Any],
    limit: int | None = None,
    *,
    verify_ssl: bool | None = None,
) -> list[dict]:
    """Fetches recent tenders and filters them locally based on profile criteria."""
    all_tenders = fetch_tenders(verify_ssl=verify_ssl)
    
    matched: list[dict] = []
    seen: set[str] = set()
    
    # We do simple in-memory keyword matching for profiles
    for profile in profiles:
        # Profile keywords compiled list
        keywords = [kw.lower() for kw in (profile.keywords or [])]
        neg_keywords = [kw.lower() for kw in (profile.negative_keywords or [])]
        
        for t in all_tenders:
            ext_id = t["external_id"]
            if ext_id in seen:
                continue
                
            # 1. Match region if profile restricts regions
            if profile.regions and t["region"] not in profile.regions:
                continue
                
            # 2. Match title keywords
            title_lower = t["title"].lower()
            
            # Simple matching logic similar to scoring
            has_positive = any(kw in title_lower for kw in keywords) if keywords else True
            has_negative = any(kw in title_lower for kw in neg_keywords) if neg_keywords else False
            
            if has_positive and not has_negative:
                seen.add(ext_id)
                matched.append(t)
                
                if limit is not None and len(matched) >= limit:
                    return matched
                    
    return matched
