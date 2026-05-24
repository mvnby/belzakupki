from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import os
import random
import time
from urllib.parse import urlencode, urljoin

from loguru import logger
import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from worker.sources.base import extract_external_id, normalize_html_text
from worker.sources.region_codes import ICETRADE_REGION_MAP, map_regions

BASE_URL = "https://icetrade.by"
URL = f"{BASE_URL}/search/auctions"
VITEBSK_REGION_ID = "2"
HVAC_VITEBSK_TERMS = (
    "кондиционер",
    "сплит-система",
    "сплит система",
    "вентиляционное оборудование",
)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 OPR/109.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


@dataclass(frozen=True)
class IcetradeSearch:
    text: str | None = None
    regions: tuple[str, ...] = ()
    okrb: str | None = None

    @property
    def label(self) -> str:
        parts: list[str] = []

        if self.text:
            parts.append(f"text={self.text}")

        if self.regions:
            parts.append("regions=" + ",".join(self.regions))

        if self.okrb:
            parts.append(f"okrb={self.okrb}")

        return "; ".join(parts) or "posted"


def should_verify_ssl() -> bool:
    value = os.getenv("GOSZAKUPKI_VERIFY_SSL", "true").casefold()
    return value not in {"0", "false", "no"}


def build_headers() -> dict[str, str]:
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    return headers


def _apply_throttling() -> None:
    min_delay = float(os.getenv("ICETRADE_MIN_DELAY", "1.0"))
    max_delay = float(os.getenv("ICETRADE_MAX_DELAY", "3.0"))
    if max_delay > min_delay:
        delay = random.uniform(min_delay, max_delay)
        logger.debug(f"IceTrade throttling: sleeping for {delay:.2f}s...")
        time.sleep(delay)
    elif min_delay > 0:
        logger.debug(f"IceTrade throttling: sleeping for {min_delay:.2f}s...")
        time.sleep(min_delay)


def _create_client(verify_ssl: bool) -> httpx.Client:
    proxy = os.getenv("ICETRADE_PROXY")
    return httpx.Client(
        follow_redirects=True,
        timeout=15,
        verify=verify_ssl,
        proxy=proxy,
    )


def is_retryable_exception(exception: Exception) -> bool:
    if isinstance(exception, httpx.HTTPStatusError):
        return exception.response.status_code in (429, 502, 503, 504)
    return isinstance(exception, (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError))


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception(is_retryable_exception),
    reraise=True,
)
def _execute_request(
    client: httpx.Client,
    method: str,
    url: str,
    **kwargs,
) -> httpx.Response:
    _apply_throttling()
    headers = kwargs.pop("headers", None) or {}
    headers.update(build_headers())
    kwargs["headers"] = headers
    
    logger.debug(f"IceTrade request: {method} {url} with User-Agent: {headers.get('User-Agent')}")
    response = client.request(method, url, **kwargs)
    response.raise_for_status()
    return response


def build_search_params(search: IcetradeSearch | None) -> list[tuple[str, str]]:
    params = [
        ("search", "Найти"),
        ("zakup_type[1]", "1"),
        ("zakup_type[2]", "1"),
        ("t[Trade]", "1"),
        ("t[eTrade]", "1"),
        ("t[Request]", "1"),
        ("t[singleSource]", "1"),
        ("t[Auction]", "1"),
        ("t[Other]", "1"),
        ("t[contractingTrades]", "1"),
        ("t[socialOrder]", "1"),
        ("t[negotiations]", "1"),
        ("sort", "num:desc"),
        ("onPage", "20"),
    ]

    if search:
        if search.text:
            params.append(("search_text", search.text))
        if search.okrb:
            params.append(("okrb", search.okrb))
        for region in search.regions:
            mapped_region = ICETRADE_REGION_MAP.get(region, region)
            params.append((f"r[{mapped_region}]", mapped_region))
    else:
        # Если поиск не задан, ищем по всем регионам
        for r in range(1, 8):
            params.append((f"r[{r}]", str(r)))

    return params


def build_search_url(search: IcetradeSearch | None) -> str:
    params = build_search_params(search)
    return f"{URL}?{urlencode(params)}"


def parse_tenders_html(
    html: str,
    *,
    limit: int | None = None,
    base_url: str = BASE_URL,
    search: IcetradeSearch | None = None,
) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    tenders: list[dict] = []

    # Находим таблицу с тендерами
    table = soup.select_one("table#auctions-list")
    if not table:
        return tenders

    rows = table.select("tr")
    for row in rows:
        # Пропускаем строку заголовка (она содержит th)
        if row.find("th"):
            continue

        cols = row.find_all("td")
        if len(cols) < 6:
            continue

        link_tag = cols[0].find("a")
        if not link_tag or not link_tag.get("href"):
            continue

        # Убираем подсветку
        for highlight in link_tag.select(".hlt"):
            highlight.unwrap()

        title = normalize_html_text(link_tag.get_text("", strip=False))
        url = urljoin(base_url, link_tag["href"])
        
        customer_name = normalize_html_text(cols[1].get_text(" ", strip=True))
        source_number = normalize_html_text(cols[3].get_text(" ", strip=True))
        
        estimated_value = normalize_html_text(cols[4].get_text(" ", strip=True))
        deadline = normalize_html_text(cols[5].get_text(" ", strip=True))

        tenders.append(
            {
                "external_id": extract_external_id(url),
                "title": title,
                "customer_name": customer_name,
                "url": url,
                "status": "posted",
                "source_number": source_number,
                "procedure_type": "Закупка Icetrade",
                "deadline": deadline,
                "estimated_value": estimated_value,
                "search": search.label if search else None,
                "search_text": search.text if search else None,
                "search_regions": list(search.regions) if search else [],
                "search_industry": None,
            }
        )

        if limit is not None and len(tenders) >= limit:
            break

    return tenders


def fetch_tenders(
    limit: int | None = None,
    *,
    search: IcetradeSearch | None = None,
    verify_ssl: bool | None = None,
) -> list[dict]:
    verify = should_verify_ssl() if verify_ssl is None else verify_ssl

    with _create_client(verify) as client:
        response = _execute_request(client, "GET", build_search_url(search))
        return parse_tenders_html(response.text, limit=limit, search=search)


def fetch_tenders_for_searches(
    searches: Iterable[IcetradeSearch],
    *,
    limit: int | None = None,
    verify_ssl: bool | None = None,
) -> list[dict]:
    verify = should_verify_ssl() if verify_ssl is None else verify_ssl
    tenders: list[dict] = []
    seen_external_ids: set[str] = set()

    with _create_client(verify) as client:
        for search in searches:
            remaining = None if limit is None else limit - len(tenders)
            if remaining is not None and remaining <= 0:
                break

            response = _execute_request(client, "GET", build_search_url(search))

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


def build_hvac_vitebsk_searches() -> list[IcetradeSearch]:
    searches = [
        IcetradeSearch(text=term, regions=(VITEBSK_REGION_ID,))
        for term in HVAC_VITEBSK_TERMS
    ]
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


def build_dynamic_searches(profiles: Iterable[Any]) -> list[IcetradeSearch]:
    searches = []
    for profile in profiles:
        regions = tuple(profile.regions) if profile.regions else ()
        
        # Фильтруем только коды ОКРБ (содержащие точки)
        okrb_codes = [c for c in (profile.categories or []) if "." in c]
        
        # 1. Поиски по кодам ОКРБ
        for okrb in okrb_codes:
            searches.append(IcetradeSearch(okrb=okrb, regions=regions))
            
        # 2. Поиски по ключевым словам (как дополнение)
        for kw in (profile.keywords or []):
            searches.append(IcetradeSearch(text=kw, regions=regions))
    
    if not searches:
        searches.append(IcetradeSearch())
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
    
    with _create_client(verify) as client:
        response = _execute_request(client, "GET", tender_url)
        
        soup = BeautifulSoup(response.text, "html.parser")
        attachments = []
        
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "/getFile/" in href:
                file_url = urljoin(tender_url, href)
                if "/getFile/" in file_url:
                    file_url = file_url.replace("/getFile/", "/download/")
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
        response = client.get(tender_url)
        response.raise_for_status()
        
        return parse_tender_details_html(response.text)


def parse_tender_result_html(html: str) -> dict[str, Any] | None:
    import re
    soup = BeautifulSoup(html, "html.parser")
    
    status = "Состоялась"
    winner_name = None
    winner_unp = None
    contract_price = None
    currency = "BYN"
    participants = []
    others_text = ""

    # Find tables that contain result details
    target_table = None
    for table in soup.find_all("table"):
        table_text = table.get_text(" ", strip=True).lower()
        if "результат процедуры закупки" in table_text or "участники, с которыми заключен договор" in table_text:
            target_table = table
            break

    if not target_table:
        return None

    rows = target_table.find_all("tr")
    for idx, row in enumerate(rows):
        cells = [normalize_html_text(c.get_text(" ", strip=True)) for c in row.find_all(["td", "th"])]
        if not cells:
            continue

        cells_lower = [c.lower() for c in cells]

        # 1. Check for winner and price headers
        if len(cells) >= 4 and any("участники" in h for h in cells_lower[2:3]) and any("цена" in h for h in cells_lower[3:4]):
            # The next row contains the winner and contract price
            if idx + 1 < len(rows):
                next_cells = [normalize_html_text(c.get_text(" ", strip=True)) for c in rows[idx+1].find_all(["td", "th"])]
                if len(next_cells) >= 4:
                    winner_name = next_cells[2]
                    contract_price = next_cells[3]
                    curr_m = re.search(r"(BYN|USD|EUR|RUB|rub|byn)", str(contract_price), re.IGNORECASE)
                    if curr_m:
                        currency = curr_m.group(1).upper()

        # 2. Check for result status
        for cell_idx, cell in enumerate(cells):
            if "результат процедуры закупки" in cell.lower() and cell_idx + 1 < len(cells):
                res_val = cells[cell_idx + 1]
                if "состоялась" in res_val.lower():
                    status = "Состоялась"
                elif "несостоявшейся" in res_val.lower() or "не состоялась" in res_val.lower():
                    status = "Признан несостоявшимся"
                elif "отменен" in res_val.lower() or "отменена" in res_val.lower():
                    status = "Отменена"
                else:
                    status = res_val

        # 3. Check for Winner UNP
        if any("унп участников" in c.lower() for c in cells) and len(cells) >= 2:
            winner_unp = cells[1]

        # 4. Check for other participants text
        if any("иные участники" in c.lower() for c in cells) and len(cells) >= 2:
            others_text = cells[1]

    # Clean price value to decimal if possible
    contract_price_decimal = None
    if contract_price:
        clean_price_str = re.sub(r"[^\d\.,]", "", str(contract_price)).replace(",", ".")
        try:
            from decimal import Decimal
            contract_price_decimal = Decimal(clean_price_str)
        except Exception:
            pass

    # Build participants list
    if winner_name and winner_name != "-":
        participants.append({
            "name": winner_name,
            "unp": winner_unp if winner_unp and winner_unp != "-" else None,
            "price": contract_price,
            "winner": True
        })

    # Parse other participants
    if others_text:
        # Split by ';' to separate companies
        # Each part can be: ООО «НОВАСТАР», УНП 491319658 246007, г. Гомель - 39120,00 (отклонен)
        parts = others_text.split(";")
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            # Simple heuristics to find name, UNP and price
            # Extract UNP
            unp_m = re.search(r"УНП\s*(\d+)", part)
            p_unp = unp_m.group(1) if unp_m else None
            
            # Extract price: usually after '-' or at the end
            # e.g. - 38137,00 or - 27700,00 (отклонен)
            price_m = re.search(r"-\s*([\d\s\.,]+)", part)
            p_price = price_m.group(1).strip() if price_m else None
            
            # Extract name: everything before UNP or before '-'
            p_name = part
            if unp_m:
                p_name = part.split("УНП")[0].strip(", ")
            elif price_m:
                p_name = part.split("-")[0].strip(", ")
                
            # Clean name
            p_name = re.sub(r"\s+", " ", p_name).strip()
            
            # Winner status
            p_winner = False
            if winner_name and p_name.lower() in winner_name.lower():
                p_winner = True

            # Avoid adding winner twice
            if p_winner and any(p["winner"] for p in participants):
                continue

            participants.append({
                "name": p_name,
                "unp": p_unp,
                "price": p_price,
                "winner": p_winner
            })

    return {
        "status": status,
        "winner_name": winner_name if winner_name != "-" else None,
        "winner_unp": winner_unp if winner_unp != "-" else None,
        "contract_price": contract_price_decimal,
        "currency": currency,
        "participants": participants
    }


def fetch_tender_result(
    tender_url: str,
    *,
    verify_ssl: bool | None = None,
) -> dict[str, Any] | None:
    verify = should_verify_ssl() if verify_ssl is None else verify_ssl

    with _create_client(verify) as client:
        response = _execute_request(client, "GET", tender_url)

        soup = BeautifulSoup(response.text, "html.parser")
        
        # Search for result link
        result_url = None
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "viewResult" in href:
                result_url = urljoin(tender_url, href)
                break

        if not result_url:
            return None

        # Fetch result page
        res_response = _execute_request(client, "GET", result_url)

        parsed = parse_tender_result_html(res_response.text)
        if parsed:
            parsed["result_url"] = result_url
        return parsed


