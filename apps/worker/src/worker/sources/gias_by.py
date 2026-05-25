from __future__ import annotations

from collections.abc import Iterable
from typing import Any
import os
from datetime import datetime, timezone
from loguru import logger
import httpx

BASE_URL = "https://gias.by"
SEARCH_API_URL = f"{BASE_URL}/search/api/v1/search/purchases"
DETAIL_API_URL = f"{BASE_URL}/purchase/api/v1/purchase"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"

GIAS_PROCEDURE_TYPES = {
    1: "открытый конкурс",
    2: "электронный аукцион",
    3: "процедура запроса ценовых предложений",
    4: "процедура закупки из одного источника",
    5: "биржевые торги",
    6: "двухэтапный конкурс",
    7: "конкурс с ограниченным участием",
    8: "процедура закупки из одного источника на ЭТП",
}


def should_verify_ssl() -> bool:
    value = os.getenv("GOSZAKUPKI_VERIFY_SSL", "true").casefold()
    return value not in {"0", "false", "no"}


def extract_region_fallback(item: dict) -> str | None:
    """Extracts canonical region code from customer name/location text as fallback."""
    org = item.get("organizator") or {}
    location = org.get("location") or ""
    name = org.get("name") or ""
    text = (name + " " + location).lower()
    
    if "брест" in text:
        return "1"
    if "витеб" in text:
        return "2"
    if "гоме" in text:
        return "3"
    if "гродн" in text:
        return "4"
    if "могил" in text:
        return "7"
    if "минс" in text or "белфармация" in text or "белмедтехника" in text or "белжелдорснаб" in text:
        if "област" in text or "район" in text:
            return "6"
        return "5"
    return None


def map_gias_tender(item: dict, detail: dict | None = None) -> dict:
    """Maps the raw JSON items from GIAS search/detail to canonical procurement data format."""
    d = detail or item
    purchase_gias_id = d.get("purchaseGiasId") or item.get("purchaseGiasId")
    external_id = str(purchase_gias_id)
    
    title = d.get("title") or item.get("title")
    org = d.get("organizator") or item.get("organizator") or {}
    customer_name = org.get("name")
    url = f"{BASE_URL}/gias/#/purchase/current/{purchase_gias_id}"
    status = d.get("stateName") or item.get("stateName")
    
    tender_form = d.get("tenderForm")
    procedure_type = GIAS_PROCEDURE_TYPES.get(tender_form, "Не указана")
    
    # 1. Map source_number
    source_number = d.get("publicPurchaseNumber") or item.get("publicPurchaseNumber")
    
    # 2. Map attachments
    attachments = []
    for link in d.get("links", []):
        if link.get("link"):
            attachments.append({
                "name": link.get("name") or link.get("description") or "Документ",
                "url": link.get("link")
            })
            
    # 3. Map lots
    lots = []
    for lot in d.get("lots", []):
        unit_name = lot.get("unit", {}).get("name") if lot.get("unit") else ""
        volume = lot.get("volume")
        qty_str = f"{volume} {unit_name}".strip() if volume is not None else unit_name
        
        okrb_list = lot.get("codeOKPB") or []
        okrb_str = ", ".join(str(o) for o in okrb_list)
        
        lots.append({
            "number": str(lot.get("lotNumber") or ""),
            "name": lot.get("titleLot"),
            "quantity": qty_str,
            "estimated_value": lot.get("price"),
            "okrb": okrb_str
        })
        
    # 4. Map contacts
    contacts = None
    contact_org = d.get("contactOrganizer")
    if contact_org:
        if isinstance(contact_org, dict):
            contacts = {
                "name": contact_org.get("name") or contact_org.get("fullName") or "",
                "phone": contact_org.get("phone") or contact_org.get("telephone") or "",
                "email": contact_org.get("email") or ""
            }
        else:
            contacts = {"name": str(contact_org), "phone": "", "email": ""}
            
    # 5. Map delivery terms
    deliveries = set(lot.get("deliveryLot") for lot in d.get("lots", []) if lot.get("deliveryLot"))
    delivery_terms = ", ".join(sorted(list(deliveries))) if deliveries else None
    
    # 6. Map payment terms and funding source
    funding_sources = set()
    for lot in d.get("lots", []):
        for fs in lot.get("financeSource", []):
            if fs.get("budgetCost", 0) > 0:
                funding_sources.add("Бюджетные средства")
            if fs.get("fundCost", 0) > 0 or fs.get("innerCost", 0) > 0:
                funding_sources.add("Собственные/Внебюджетные средства")
    funding_source = " + ".join(sorted(list(funding_sources))) if funding_sources else "Не указан"
    
    payment_terms = "см. документацию" if attachments else None
    
    sum_lot_obj = d.get("sumLot") or item.get("sumLot") or {}
    estimated_value = sum_lot_obj.get("sumLot")
    if estimated_value is not None:
        estimated_value = float(estimated_value)
    
    currency = d.get("codeCurrencyToEtp")
    if currency == "933":
        currency = "BYN"
    elif not currency:
        currency = "BYN"
        
    dt_create = d.get("dtCreate") or item.get("dtCreate")
    published_at = None
    if dt_create:
        published_at = datetime.fromtimestamp(dt_create / 1000, tz=timezone.utc)
        
    request_date = d.get("requestDate") or item.get("requestDate")
    deadline_at = None
    if request_date:
        deadline_at = datetime.fromtimestamp(request_date / 1000, tz=timezone.utc)
        
    gias_region = d.get("region")
    region = None
    if gias_region is not None:
        gias_region_str = str(gias_region)
        gias_to_canonical = {
            "1": "1",
            "2": "2",
            "3": "3",
            "4": "4",
            "5": "6",  # Минская обл.
            "6": "7",  # Могилевская обл.
            "7": "5"   # г. Минск
        }
        region = gias_to_canonical.get(gias_region_str)
        
    if not region:
        region = extract_region_fallback(d)
        
    return {
        "external_id": external_id,
        "source_number": source_number,
        "title": title,
        "customer_name": customer_name,
        "url": url,
        "status": status,
        "procedure_type": procedure_type,
        "funding_source": funding_source,
        "estimated_value": estimated_value,
        "currency": currency,
        "published_at": published_at,
        "deadline_at": deadline_at,
        "region": region,
        "attachments": attachments,
        "contacts": contacts,
        "delivery_terms": delivery_terms,
        "payment_terms": payment_terms,
        "lots": lots,
        "raw_data": d
    }


def fetch_tenders(
    limit: int | None = None,
    *,
    verify_ssl: bool | None = None,
) -> list[dict]:
    """Fetches list of tenders from GIAS live API."""
    verify = should_verify_ssl() if verify_ssl is None else verify_ssl
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json"
    }
    
    page_size = limit if limit is not None and limit > 0 else 50
    payload = {
        "page": 0,
        "pageSize": page_size,
        "sortField": "dtCreate",
        "sortOrder": "DESC"
    }
    
    logger.info(f"Fetching GIAS tenders from {SEARCH_API_URL}...")
    
    tenders: list[dict] = []
    try:
        with httpx.Client(
            follow_redirects=True,
            headers=headers,
            timeout=30.0,
            verify=verify,
        ) as client:
            r = client.post(SEARCH_API_URL, json=payload)
            r.raise_for_status()
            
            search_data = r.json()
            items = search_data.get("content", [])
            
            if limit is not None:
                items = items[:limit]
                
            logger.info(f"Found {len(items)} items in search. Fetching details...")
            
            for item in items:
                purchase_gias_id = item.get("purchaseGiasId")
                if not purchase_gias_id:
                    continue
                    
                detail_url = f"{DETAIL_API_URL}/{purchase_gias_id}"
                try:
                    logger.debug(f"Fetching details for tender {purchase_gias_id}...")
                    r_detail = client.get(detail_url)
                    r_detail.raise_for_status()
                    detail = r_detail.json()
                except Exception as de:
                    logger.warning(f"Failed to fetch details for tender {purchase_gias_id}: {de}. Using search item fallback.")
                    detail = None
                    
                mapped = map_gias_tender(item, detail)
                tenders.append(mapped)
                
    except Exception as e:
        logger.error(f"Error fetching tenders from GIAS: {e}")
        raise
        
    return tenders


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
