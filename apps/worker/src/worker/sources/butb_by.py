from __future__ import annotations

from collections.abc import Iterable
import os
import re
from typing import Any
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
from xml.etree import ElementTree
from loguru import logger
import httpx
from bs4 import BeautifulSoup, Tag

from worker.sources.base import normalize_html_text, parse_deadline_string, select_search_results

BASE_URL = "https://zakupki.butb.by"
REGISTRY_URL = f"{BASE_URL}/auctions/reestrauctions.html"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
_REGISTRY_FORM_ID = "fra"
_REGISTRY_TABLE_ID = "fra:reestrAu"
_VIEW_STATE = "javax.faces.ViewState"
_MAX_REGISTRY_BYTES = 2 * 1024 * 1024


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
        deadline_dt = parse_deadline_string(deadline_str, require_time=True)
        deadline_day = parse_date(deadline_str) if deadline_dt is None else None
        if deadline_day is not None:
            deadline_dt = deadline_day + timedelta(days=1, seconds=-1)
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
            "deadline_date_only": deadline_day is not None,
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


def _registry_page(client: httpx.Client, method: str, **kwargs) -> bytes:
    with client.stream(method, REGISTRY_URL, **kwargs) as response:
        response.raise_for_status()
        contents = bytearray()
        for chunk in response.iter_bytes():
            if len(contents) + len(chunk) > _MAX_REGISTRY_BYTES:
                raise ValueError("BUTB registry response exceeds the size limit")
            contents.extend(chunk)
    return bytes(contents)


def _registry_form(html: str) -> Tag:
    form = BeautifulSoup(html, "html.parser").find("form", id=_REGISTRY_FORM_ID)
    if form is None:
        raise ValueError("BUTB registry search form is unavailable")
    return form


def _form_values(form: Tag) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for field in form.select("input[name]:not([disabled])"):
        input_type = field.get("type", "text")
        if input_type in {"hidden", "text"}:
            values.setdefault(field["name"], []).append(field.get("value", ""))
        elif input_type in {"checkbox", "radio"} and field.has_attr("checked"):
            # HTML submits "on" for a checked input with no explicit value.
            # An empty value clears the visible registry columns in this form.
            values.setdefault(field["name"], []).append(field.get("value", "on"))
    for field in form.select("select[name]:not([disabled])"):
        options = field.select("option[selected]:not([disabled])")
        if not options and not field.has_attr("multiple"):
            options = field.select("option:not([disabled])")[:1]
        if options:
            values[field["name"]] = [option.get("value", option.get_text()) for option in options]
    return values


def _search_action(
    client: httpx.Client, values: dict[str, list[str]], component: str, *, expand: bool = False,
) -> dict[str, str]:
    payload = {
        **values,
        _REGISTRY_FORM_ID: _REGISTRY_FORM_ID,
        "fra:j_idcl": component if expand else "",
        "javax.faces.source": component,
        "javax.faces.partial.event": "click",
        "javax.faces.partial.execute": "@all",
        "javax.faces.partial.render": "@all",
        "javax.faces.partial.ajax": "true",
        "ice.focus": component,
        "ice.event.target": component,
        "ice.event.captured": component,
        "ice.event.type": "onclick",
        "ice.event.alt": "false",
        "ice.event.ctrl": "false",
        "ice.event.shift": "false",
        "ice.event.meta": "false",
        "ice.event.x": "0",
        "ice.event.y": "0",
        "ice.event.left": "false",
        "ice.event.right": "false",
        "ice.submit.type": "ice.s",
        "ice.submit.serialization": "form",
        component: component,
    }
    response = _registry_page(client, "POST", content=urlencode(payload, doseq=True), headers={
        "Faces-Request": "partial/ajax",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Referer": REGISTRY_URL,
    })
    root = ElementTree.fromstring(response)
    updates = {node.attrib["id"]: node.text or "" for node in root.findall("./changes/update")}
    if root.tag != "partial-response" or not updates.get(_VIEW_STATE):
        raise ValueError("BUTB registry did not return its search session")
    return updates


def _subject_field(form: Tag) -> Tag | None:
    for field in form.select("input[type='text'][name]:not([disabled])"):
        for owner in (field, field.parent):
            caption = owner.find_previous_sibling()
            if caption and normalize_html_text(caption.get_text(" ", strip=True)) == "Предмет закупки":
                return field
    return None


def fetch_market_tenders(
    profiles: Iterable[Any], limit: int | None = None, *, verify_ssl: bool | None = None,
) -> list[dict]:
    """Read the first public registry page for each distinct market term."""
    terms = sorted({
        keyword.strip().casefold()
        for profile in profiles
        for keyword in profile.keywords or []
        if keyword.strip()
    })
    limit = 20 if limit is None else limit
    if not terms or limit <= 0:
        return []
    verify = should_verify_ssl() if verify_ssl is None else verify_ssl
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20, verify=verify) as client:
        form = _registry_form(_registry_page(client, "GET").decode("utf-8"))
        expand = next((
            link for link in form.select("a[id]")
            if link.get_text(" ", strip=True) == "Раскрыть форму поиска"
        ), None)
        if expand is None:
            raise ValueError("BUTB registry search control is unavailable")
        updates = _search_action(client, _form_values(form), expand["id"], expand=True)
        form = _registry_form(updates.get(_REGISTRY_FORM_ID, ""))
        field = _subject_field(form)
        submit = form.select_one("input[type='submit'][value='Искать'][id]")
        if field is None or submit is None:
            raise ValueError("BUTB registry subject search is unavailable")

        values = _form_values(form)
        pages = []
        for term in terms:
            values[field["name"]] = [term]
            values[_VIEW_STATE] = [updates[_VIEW_STATE]]
            updates = _search_action(client, values, submit["id"])
            if _REGISTRY_TABLE_ID not in updates:
                raise ValueError("BUTB registry search did not return a results page")
            pages.append(parse_tenders_html(updates[_REGISTRY_TABLE_ID]))
        return select_search_results(pages, limit, balanced=True)


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


def parse_tender_details_html(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    
    # 1. Parse Grids for general metadata
    data = {}
    grids = soup.find_all(class_=lambda c: c and "grid" in c)
    for g in grids:
        children = [normalize_html_text(c.get_text(" ", strip=True)) for c in g.find_all(recursive=False)]
        for idx, text in enumerate(children):
            clean_txt = text.strip(":")
            if clean_txt in [
                "Регистрационный номер", "Вид процедуры", "Вид процедуры закупки",
                "Состояние", "УНП", "Полное наименование", "Место нахождения",
                "Телефон", "E-mail", "Вид закупки", "Отрасль", "Наименование процедуры",
                "Наименование закупки", "Конечная дата представления информации",
                "Дата окончания приема предложений", "Дата окончания подачи предложений"
            ]:
                if idx + 1 < len(children):
                    val = children[idx+1]
                    if clean_txt in data:
                        if isinstance(data[clean_txt], list):
                            data[clean_txt].append(val)
                        else:
                            data[clean_txt] = [data[clean_txt], val]
                    else:
                        data[clean_txt] = val

    # Helper to get last item if list, else item itself
    def get_last(val):
        if isinstance(val, list):
            return val[-1]
        return val

    source_number = get_last(data.get("Регистрационный номер"))
    procedure_type = get_last(data.get("Вид закупки") or data.get("Вид процедуры") or data.get("Вид процедуры закупки"))
    status = get_last(data.get("Состояние"))
    customer_name = get_last(data.get("Полное наименование"))
    
    # Contacts
    contacts = {"name": "", "phone": "", "email": ""}
    
    phones = data.get("Телефон")
    emails = data.get("E-mail")
    
    contacts["phone"] = get_last(phones) if phones else ""
    contacts["email"] = get_last(emails) if emails else ""
    
    # Fallback contact parsing from text with regex if empty
    if not contacts["phone"] or not contacts["email"]:
        body_text = normalize_html_text(soup.get_text(" ", strip=True))
        phone_match = re.search(r"Телефон\s*([+\d\s\(\)-]{7,25})", body_text, re.IGNORECASE)
        email_match = re.search(r"E-mail\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,4})", body_text, re.IGNORECASE)
        if phone_match and not contacts["phone"]:
            contacts["phone"] = phone_match.group(1).strip()
        if email_match and not contacts["email"]:
            contacts["email"] = email_match.group(1).strip()
            
    # Lots & Deliveries
    lots = []
    deliveries = set()
    tables = soup.find_all("table")
    
    for table in tables:
        # SKIP outer layout tables containing nested tables
        if table.find("table") is not None:
            continue
            
        thead = table.find("thead")
        if not thead:
            continue
        headers = [normalize_html_text(th.get_text(" ", strip=True)) for th in thead.find_all("th")]
        if any("№ лота" in h or "предмет закупки" in h.lower() for h in headers):
            h_lower = [h.lower() for h in headers]
            num_idx = h_lower.index("№ лота") if "№ лота" in h_lower else 0
            okrb_idx = h_lower.index("код окрб") if "код окрб" in h_lower else 1
            name_idx = h_lower.index("предмет закупки") if "предмет закупки" in h_lower else 2
            qty_idx = h_lower.index("количество (объем)") if "количество (объем)" in h_lower else 3
            delivery_idx = h_lower.index("место поставки") if "место поставки" in h_lower else -1
            
            value_idx = -1
            for idx, h in enumerate(h_lower):
                if "стоимость" in h or "цена" in h:
                    value_idx = idx
                    
            tbody = table.find("tbody")
            rows = tbody.find_all("tr") if tbody else table.find_all("tr")
            rows = [r for r in rows if not r.find("th")]
            
            for row in rows:
                tds = row.find_all("td")
                if len(tds) > max(num_idx, name_idx):
                    lot_num = normalize_html_text(tds[num_idx].get_text(" ", strip=True)) if len(tds) > num_idx else ""
                    okrb = normalize_html_text(tds[okrb_idx].get_text(" ", strip=True)) if len(tds) > okrb_idx else ""
                    name = normalize_html_text(tds[name_idx].get_text(" ", strip=True)) if len(tds) > name_idx else ""
                    qty = normalize_html_text(tds[qty_idx].get_text(" ", strip=True)) if len(tds) > qty_idx else ""
                    val = normalize_html_text(tds[value_idx].get_text(" ", strip=True)) if value_idx != -1 and len(tds) > value_idx else ""
                    delivery = normalize_html_text(tds[delivery_idx].get_text(" ", strip=True)) if delivery_idx != -1 and len(tds) > delivery_idx else ""
                    
                    if delivery:
                        deliveries.add(delivery)
                        
                    lots.append({
                        "number": lot_num,
                        "okrb": okrb,
                        "name": name,
                        "quantity": qty,
                        "estimated_value": val
                    })
            break
            
    delivery_terms = ", ".join(sorted(list(deliveries))) if deliveries else None

    # Document Attachments
    attachments = []
    for table in tables:
        if table.find("table") is not None:
            continue
            
        thead = table.find("thead")
        if not thead:
            continue
        headers = [normalize_html_text(th.get_text(" ", strip=True)) for th in thead.find_all("th")]
        if any("имя файла" in h.lower() or "наименование документа" in h.lower() for h in headers):
            h_lower = [h.lower() for h in headers]
            name_idx = h_lower.index("наименование документа") if "наименование документа" in h_lower else -1
            file_idx = h_lower.index("имя файла") if "имя файла" in h_lower else -1
            
            tbody = table.find("tbody")
            rows = tbody.find_all("tr") if tbody else table.find_all("tr")
            rows = [r for r in rows if not r.find("th")]
            
            for row in rows:
                tds = row.find_all("td")
                link = row.find("a", href=True)
                if link:
                    href = link["href"]
                    if href.startswith("/"):
                        href = "https://zakupki.butb.by" + href
                    if ";jsessionid=" in href:
                        parts = href.split(";jsessionid=")
                        path_part = parts[0]
                        query_part = parts[1].split("?")[-1] if "?" in parts[1] else ""
                        if query_part:
                            sep = "&" if "?" in path_part else "?"
                            href = path_part + sep + query_part
                        else:
                            href = path_part
                        
                    doc_name = ""
                    if name_idx != -1 and len(tds) > name_idx:
                        doc_name = normalize_html_text(tds[name_idx].get_text(" ", strip=True))
                    if not doc_name:
                        doc_name = normalize_html_text(link.get_text(" ", strip=True))
                        
                    attachments.append({
                        "name": doc_name,
                        "url": href
                    })
            break

    # Funding source classification
    funding_source = "Не указан"
    proc_type_val = data.get("Вид закупки")
    if proc_type_val:
        if "бюджет" in proc_type_val.lower():
            funding_source = "Бюджетные средства"
        elif "собствен" in proc_type_val.lower():
            funding_source = "Собственные средства"
            
    payment_terms = "см. документацию" if attachments else None
    
    return {
        "source_number": source_number,
        "procedure_type": procedure_type,
        "status": status,
        "customer_name": customer_name,
        "contacts": contacts if any(contacts.values()) else None,
        "delivery_terms": delivery_terms,
        "payment_terms": payment_terms,
        "funding_source": funding_source,
        "attachments": attachments,
        "lots": lots
    }


def fetch_tender_details(
    tender_url: str,
    *,
    verify_ssl: bool | None = None,
) -> dict[str, Any]:
    verify = should_verify_ssl() if verify_ssl is None else verify_ssl
    headers = {"User-Agent": USER_AGENT}
    
    with httpx.Client(
        follow_redirects=True,
        headers=headers,
        timeout=20,
        verify=verify,
    ) as client:
        # Establish session cookies
        client.get(f"{BASE_URL}/").raise_for_status()
        
        r = client.get(tender_url)
        r.raise_for_status()
        
        return parse_tender_details_html(r.text)


def fetch_tender_attachments(
    tender_url: str,
    *,
    verify_ssl: bool | None = None,
) -> list[dict[str, str]]:
    details = fetch_tender_details(tender_url, verify_ssl=verify_ssl)
    return details.get("attachments", [])

