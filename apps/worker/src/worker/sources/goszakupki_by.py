from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import os
from urllib.parse import urlencode, urljoin

import httpx
from bs4 import BeautifulSoup

from worker.sources.base import extract_external_id, normalize_html_text
from worker.sources.region_codes import GOSZAKUPKI_REGION_MAP, map_regions

BASE_URL = "https://goszakupki.by"
URL = f"{BASE_URL}/tenders/posted"
USER_AGENT = "belzakupki/0.1 (+https://github.com/mvnby/belzakupki)"
VITEBSK_REGION_ID = "2"
HVAC_INDUSTRY_ID = "189"
HVAC_VITEBSK_TERMS = (
    "кондиционер",
    "сплит-система",
    "сплит система",
    "вентиляционное оборудование",
)


@dataclass(frozen=True)
class GoszakupkiSearch:
    text: str | None = None
    regions: tuple[str, ...] = ()
    industry: str | None = None
    okrb: str | None = None

    @property
    def label(self) -> str:
        parts: list[str] = []

        if self.text:
            parts.append(f"text={self.text}")

        if self.regions:
            parts.append("regions=" + ",".join(self.regions))

        if self.industry:
            parts.append(f"industry={self.industry}")

        if self.okrb:
            parts.append(f"okrb={self.okrb}")

        return "; ".join(parts) or "posted"


def should_verify_ssl() -> bool:
    value = os.getenv("GOSZAKUPKI_VERIFY_SSL", "true").casefold()

    return value not in {"0", "false", "no"}


def build_headers() -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT}
    cookie = os.getenv("GOSZAKUPKI_COOKIE")

    if cookie:
        headers["Cookie"] = cookie

    return headers


def build_search_params(search: GoszakupkiSearch | None) -> list[tuple[str, str]]:
    if search is None:
        return []

    params: list[tuple[str, str]] = []

    if search.text:
        params.append(("TendersSearch[text]", search.text))

    for region in search.regions:
        mapped_region = GOSZAKUPKI_REGION_MAP.get(region, region)
        params.append(("TendersSearch[region][]", mapped_region))

    if search.industry:
        params.append(("TendersSearch[industry]", search.industry))

    if search.okrb:
        params.append(("TendersSearch[okrb]", search.okrb))

    return params


def build_search_url(search: GoszakupkiSearch | None) -> str:
    params = build_search_params(search)

    if not params:
        return URL

    return f"{URL}?{urlencode(params)}"


def parse_tenders_html(
    html: str,
    *,
    limit: int | None = None,
    base_url: str = BASE_URL,
    search: GoszakupkiSearch | None = None,
) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    tenders: list[dict] = []

    rows = soup.select("table tbody tr")

    for row in rows:
        cols = row.find_all("td")

        if len(cols) < 2:
            continue

        number_text = cols[0].get_text("\n", strip=True)
        details_text = cols[1].get_text("\n", strip=True)
        link_tag = cols[1].find("a")

        if not details_text or link_tag is None or not link_tag.get("href"):
            continue

        for highlight in link_tag.select(".hlt"):
            highlight.unwrap()

        title = normalize_html_text(link_tag.get_text("", strip=False))
        url = urljoin(base_url, link_tag["href"])
        details_lines = [line for line in details_text.splitlines() if line.strip()]

        tenders.append(
            {
                "external_id": extract_external_id(url),
                "title": title,
                "customer_name": details_lines[0] if details_lines else None,
                "url": url,
                "status": (
                    cols[3].get_text(" ", strip=True) if len(cols) > 3 else "posted"
                ),
                "source_number": number_text.splitlines()[0] if number_text else None,
                "procedure_type": (
                    cols[2].get_text(" ", strip=True) if len(cols) > 2 else None
                ),
                "deadline": cols[4].get_text(" ", strip=True) if len(cols) > 4 else None,
                "estimated_value": (
                    cols[5].get_text(" ", strip=True) if len(cols) > 5 else None
                ),
                "search": search.label if search else None,
                "search_text": search.text if search else None,
                "search_regions": list(search.regions) if search else [],
                "search_industry": search.industry if search else None,
            }
        )

        if limit is not None and len(tenders) >= limit:
            break

    return tenders


def fetch_tenders(
    limit: int | None = None,
    *,
    search: GoszakupkiSearch | None = None,
    verify_ssl: bool | None = None,
) -> list[dict]:
    verify = should_verify_ssl() if verify_ssl is None else verify_ssl

    with httpx.Client(
        follow_redirects=True,
        headers=build_headers(),
        timeout=10,
        verify=verify,
    ) as client:
        client.get(BASE_URL).raise_for_status()
        response = client.get(build_search_url(search))
        response.raise_for_status()

        if response.url.path == "/site/login":
            raise RuntimeError(
                "goszakupki.by redirected to login after session warm-up"
            )

        return parse_tenders_html(response.text, limit=limit, search=search)


def fetch_tenders_for_searches(
    searches: Iterable[GoszakupkiSearch],
    *,
    limit: int | None = None,
    verify_ssl: bool | None = None,
) -> list[dict]:
    verify = should_verify_ssl() if verify_ssl is None else verify_ssl
    tenders: list[dict] = []
    seen_external_ids: set[str] = set()

    with httpx.Client(
        follow_redirects=True,
        headers=build_headers(),
        timeout=10,
        verify=verify,
    ) as client:
        client.get(BASE_URL).raise_for_status()

        for search in searches:
            remaining = None if limit is None else limit - len(tenders)

            if remaining is not None and remaining <= 0:
                break

            response = client.get(build_search_url(search))
            response.raise_for_status()

            if response.url.path == "/site/login":
                raise RuntimeError(
                    "goszakupki.by redirected to login after session warm-up"
                )

            items = parse_tenders_html(
                response.text,
                search=search,
            )

            for item in items:
                external_id = item["external_id"]

                if external_id in seen_external_ids:
                    continue

                seen_external_ids.add(external_id)
                tenders.append(item)

                if limit is not None and len(tenders) >= limit:
                    break

    return tenders


def build_hvac_vitebsk_searches() -> list[GoszakupkiSearch]:
    searches = [
        GoszakupkiSearch(text=term, regions=(VITEBSK_REGION_ID,))
        for term in HVAC_VITEBSK_TERMS
    ]
    searches.append(
        GoszakupkiSearch(regions=(VITEBSK_REGION_ID,), industry=HVAC_INDUSTRY_ID)
    )

    return searches


def fetch_hvac_vitebsk_tenders(
    limit: int | None = None,
    *,
    verify_ssl: bool | None = None,
) -> list[dict]:
    return fetch_tenders_for_searches(
        build_hvac_vitebsk_searches(),
        limit=limit,
        verify_ssl=verify_ssl,
    )


def build_dynamic_searches(profiles: Iterable[Any]) -> list[GoszakupkiSearch]:
    searches = []
    for profile in profiles:
        regions = tuple(profile.regions) if profile.regions else ()
        
        okrb_codes = [c for c in (profile.categories or []) if "." in c]
        industry_codes = [c for c in (profile.categories or []) if "." not in c]
        
        # 1. Поиски по кодам ОКРБ
        for okrb in okrb_codes:
            searches.append(GoszakupkiSearch(okrb=okrb, regions=regions))
            
        # 2. Поиски по отраслям (устаревшие коды ИД)
        for ind in industry_codes:
            searches.append(GoszakupkiSearch(industry=ind, regions=regions))
            
        # 3. Поиски по ключевым словам (как дополнение)
        for kw in (profile.keywords or []):
            searches.append(GoszakupkiSearch(text=kw, regions=regions))
    
    if not searches:
        searches.append(GoszakupkiSearch())
    return searches


def fetch_dynamic_tenders(
    profiles: Iterable[Any],
    limit: int | None = None,
    *,
    verify_ssl: bool | None = None,
) -> list[dict]:
    return fetch_tenders_for_searches(
        build_dynamic_searches(profiles),
        limit=limit,
        verify_ssl=verify_ssl,
    )


def fetch_tender_attachments(
    tender_url: str,
    *,
    verify_ssl: bool | None = None,
) -> list[dict[str, str]]:
    verify = should_verify_ssl() if verify_ssl is None else verify_ssl
    headers = build_headers()
    
    with httpx.Client(
        follow_redirects=True,
        headers=headers,
        timeout=15,
        verify=verify,
    ) as client:
        # Warm up session
        client.get(BASE_URL).raise_for_status()
        response = client.get(tender_url)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        attachments = []
        
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "/get-file/" in href:
                file_url = urljoin(tender_url, href)
                if "download=1" not in file_url:
                    file_url += "&download=1" if "?" in file_url else "?download=1"
                file_name = normalize_html_text(link.get_text("", strip=False)) or href.split("/")[-1]
                attachments.append({
                    "name": file_name,
                    "url": file_url,
                })
        return attachments


def parse_tender_details_html(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    
    contacts = {"name": "", "phone": "", "email": ""}
    delivery_terms = ""
    payment_terms = ""
    lots = []
    
    # 1. Parse DetailView tables for contacts and terms
    for row in soup.find_all("tr"):
        th = row.find(["th", "td"])
        if not th:
            continue
        th_text = th.get_text(" ", strip=True).lower()
        td = row.find_all(["td", "th"])
        if len(td) < 2:
            continue
        td_val = normalize_html_text(td[1].get_text(" ", strip=True))
        if not td_val:
            continue
            
        # Contacts check
        if "контакт" in th_text and not contacts["name"]:
            contacts["name"] = td_val
        elif "телефон" in th_text and not contacts["phone"]:
            contacts["phone"] = td_val
        elif ("email" in th_text or "e-mail" in th_text or "электронн" in th_text) and not contacts["email"]:
            contacts["email"] = td_val
            
        # Terms check
        elif "поставк" in th_text or "доставк" in th_text:
            if delivery_terms:
                delivery_terms += f"; {td_val}"
            else:
                delivery_terms = td_val
        elif "оплат" in th_text or "финансирова" in th_text:
            if payment_terms:
                payment_terms += f"; {td_val}"
            else:
                payment_terms = td_val

    # 2. Parse Lots Table
    for table in soup.find_all("table"):
        headers = [th.get_text(" ", strip=True).lower() for th in table.find_all("th")]
        if not headers:
            first_row = table.find("tr")
            if first_row:
                headers = [td.get_text(" ", strip=True).lower() for td in first_row.find_all("td")]
                
        is_lots_table = any("лот" in h or "предмет" in h or "окрб" in h or "количество" in h for h in headers)
        if is_lots_table:
            rows = table.find_all("tr")
            for r in rows:
                cells = r.find_all("td")
                if len(cells) < 3:
                    continue
                
                lot_num = ""
                lot_name = ""
                lot_qty = ""
                lot_val = ""
                lot_okrb = ""
                
                cell_texts = [normalize_html_text(c.get_text(" ", strip=True)) for c in cells]
                
                if any("лот" in text.lower() or "предмет" in text.lower() for text in cell_texts[:2]):
                    continue
                    
                for idx, text in enumerate(cell_texts):
                    if not text:
                        continue
                    
                    # Match by headers first if headers are available
                    header = headers[idx] if idx < len(headers) else ""
                    if header:
                        if any(word in header for word in ["кол-во", "количество", "объем"]) and not lot_qty:
                            lot_qty = text
                            continue
                        if "окрб" in header and not lot_okrb:
                            lot_okrb = text
                            continue
                        if any(word in header for word in ["стоимость", "сумма", "цена", "руб"]) and not lot_val:
                            lot_val = text
                            continue
                        if any(word in header for word in ["лот", "№"]) and not lot_num:
                            lot_num = text
                            continue
                        if any(word in header for word in ["предмет", "наименование", "описание"]) and not lot_name:
                            lot_name = text
                            continue

                    # Fallback to heuristics
                    if "лот" in text.lower() or (text.isdigit() and idx == 0):
                        if not lot_num:
                            lot_num = text
                    elif len(text) > 15 and not lot_name:
                        lot_name = text
                    elif ("." in text or "," in text) and len(text) < 15 and not lot_okrb and any(c.isdigit() for c in text):
                        # Avoid misidentifying quantities with periods
                        if not any(word in text.lower() for word in ["шт", "услуг", "компл"]):
                            lot_okrb = text
                        
                if not lot_num and cell_texts:
                    lot_num = f"Лот {cell_texts[0]}"
                if not lot_name and len(cell_texts) > 1:
                    lot_name = cell_texts[1]
                if not lot_qty and len(cell_texts) > 2:
                    lot_qty = cell_texts[2]
                if not lot_val and len(cell_texts) > 3:
                    lot_val = cell_texts[3]
                    
                lots.append({
                    "number": lot_num,
                    "name": lot_name,
                    "quantity": lot_qty,
                    "estimated_value": lot_val,
                    "okrb": lot_okrb
                })
            if lots:
                break
                
    from typing import Any
    return {
        "contacts": contacts,
        "delivery_terms": delivery_terms,
        "payment_terms": payment_terms,
        "lots": lots
    }


def fetch_tender_details(
    tender_url: str,
    *,
    verify_ssl: bool | None = None,
) -> dict[str, Any]:
    verify = should_verify_ssl() if verify_ssl is None else verify_ssl
    headers = build_headers()
    
    with httpx.Client(
        follow_redirects=True,
        headers=headers,
        timeout=15,
        verify=verify,
    ) as client:
        client.get(BASE_URL).raise_for_status()
        response = client.get(tender_url)
        response.raise_for_status()
        
        return parse_tender_details_html(response.text)


def parse_tender_result_html(html: str) -> dict[str, Any] | None:
    import re
    soup = BeautifulSoup(html, "html.parser")
    pre = soup.find("pre", class_="preview")
    if not pre:
        return None

    text = pre.get_text(" ", strip=True)
    
    # 1. Parse status
    status = "Состоялась"
    decision_match = re.search(
        r"(?:признать|процедуру)\s+закупки\s+.*?(состоявшейся|несостоявшейся|несостоявшимся)",
        text,
        re.IGNORECASE
    )
    if decision_match:
        decision = decision_match.group(1).lower()
        if "несостоявш" in decision:
            status = "Признан несостоявшимся"
        else:
            status = "Состоялась"
    elif "отменен" in text.lower() or "отменена" in text.lower():
        status = "Отменена"
    elif "несостоявшейся" in text.lower() or "не состоялась" in text.lower():
        status = "Признан несостоявшимся"

    # 2. Parse participants and winners
    results_section = ""
    parts = re.split(r"Результаты\s+оценки\s+и\s+сравнения\s+предложений", text, flags=re.IGNORECASE)
    if len(parts) > 1:
        results_section = parts[1]
    else:
        # Fallback to commission decision section
        parts = re.split(r"комиссия\s+приняла\s+решение", text, flags=re.IGNORECASE)
        results_section = parts[1] if len(parts) > 1 else text

    lines = [line.strip() for line in results_section.splitlines() if line.strip()]
    participants = []
    current = None

    for line in lines:
        m = re.match(r"^(\d+)\s+Код:\s+(\d+)\s+(.*?)(?:\s+Дата и время подачи:|$)", line)
        if m:
            if current:
                participants.append(current)
            
            num = m.group(1)
            code = m.group(2)
            name = m.group(3).strip()
            
            date_match = re.search(r"Дата и время подачи:\s*([\d\.\s\:]+)", line)
            date_str = date_match.group(1).strip() if date_match else None
            
            current = {
                "name": name,
                "unp": None,
                "price": None,
                "currency": None,
                "place": None,
                "winner": False,
                "address": None,
                "code": code,
                "date": date_str
            }
        elif current:
            # Address & UNP
            if "Адрес:" in line:
                addr_match = re.search(r"Адрес:\s*(.*?)(?:\s+УНП:|$)", line)
                if addr_match:
                    current["address"] = addr_match.group(1).strip()
                unp_match = re.search(r"УНП:\s*(\d+)", line)
                if unp_match:
                    current["unp"] = unp_match.group(1).strip()
                # Price from rate/offer if present in same line
                price_match = re.search(r"(?:Ценовое предложение|Ставка):\s*(.*?)$", line)
                if price_match:
                    price_val = price_match.group(1).strip()
                    current["price"] = price_val
                    # Parse currency from price
                    curr_m = re.search(r"(BYN|USD|EUR|RUB|rub|byn)", price_val, re.IGNORECASE)
                    if curr_m:
                        current["currency"] = curr_m.group(1).upper()
            
            # Place & Winner & Contract Price
            if "Место:" in line or "Выбран победителем:" in line:
                place_match = re.search(r"Место:\s*(\d+)", line)
                if place_match:
                    current["place"] = int(place_match.group(1))
                    
                winner_match = re.search(r"Выбран победителем:\s*(Да|Нет|да|нет)", line)
                if winner_match:
                    current["winner"] = winner_match.group(1).lower() == "да"
                    
                price_match = re.search(r"Цена договора:\s*(.*?)$", line)
                if price_match:
                    price_val = price_match.group(1).strip()
                    current["price"] = price_val
                    curr_m = re.search(r"(BYN|USD|EUR|RUB|rub|byn)", price_val, re.IGNORECASE)
                    if curr_m:
                        current["currency"] = curr_m.group(1).upper()

    if current:
        participants.append(current)

    # 3. Heuristic: Check explicit winner declaration text
    winner_name = None
    contract_price = None
    currency = None

    winner_decl_match = re.search(
        r"Участником-победителем\s+выбрать\s+(.*?)\s+с\s+ценой\s+договора\s+(.*?)(?:\n|$)",
        text,
        re.IGNORECASE
    )
    if winner_decl_match:
        winner_name = winner_decl_match.group(1).strip()
        price_val = winner_decl_match.group(2).strip().rstrip(".")
        contract_price = price_val
        curr_m = re.search(r"(BYN|USD|EUR|RUB|rub|byn)", price_val, re.IGNORECASE)
        if curr_m:
            currency = curr_m.group(1).upper()

    # Find winner in participants list
    winner_found = False
    for p in participants:
        if p["winner"]:
            winner_name = p["name"]
            contract_price = p["price"]
            currency = p["currency"]
            winner_found = True
            break

    if not winner_found and winner_name:
        # Match declared winner name with participants to find UNP
        for p in participants:
            if p["name"].lower() in winner_name.lower() or winner_name.lower() in p["name"].lower():
                p["winner"] = True
                winner_unp = p["unp"]
                break
        else:
            winner_unp = None
    else:
        # Get UNP from the matched participant
        winner_unp = next((p["unp"] for p in participants if p["winner"]), None)

    # Override status if winner is determined
    if winner_name:
        status = "Состоялась"

    # Clean price value to decimal if possible
    contract_price_decimal = None
    if contract_price:
        # Extract numbers, periods and commas
        clean_price_str = re.sub(r"[^\d\.,]", "", str(contract_price)).replace(",", ".")
        try:
            from decimal import Decimal
            contract_price_decimal = Decimal(clean_price_str)
        except Exception:
            pass

    return {
        "status": status,
        "winner_name": winner_name,
        "winner_unp": winner_unp,
        "contract_price": contract_price_decimal,
        "currency": currency or "BYN",
        "participants": participants
    }


def fetch_tender_result(
    tender_url: str,
    *,
    verify_ssl: bool | None = None,
) -> dict[str, Any] | None:
    verify = should_verify_ssl() if verify_ssl is None else verify_ssl
    headers = build_headers()

    with httpx.Client(
        follow_redirects=True,
        headers=headers,
        timeout=15,
        verify=verify,
    ) as client:
        # Warm up session
        client.get(BASE_URL).raise_for_status()
        response = client.get(tender_url)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        
        # Search for protocol link
        protocol_url = None
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Look for wprotocol or protocol pages
            if "wprotocol" in href or "protocol" in href:
                protocol_url = urljoin(tender_url, href)
                break

        if not protocol_url:
            return None

        # Fetch protocol page
        prot_response = client.get(protocol_url)
        prot_response.raise_for_status()

        parsed = parse_tender_result_html(prot_response.text)
        if parsed:
            parsed["protocol_url"] = protocol_url
        return parsed

