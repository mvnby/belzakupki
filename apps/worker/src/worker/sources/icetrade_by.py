from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import os
from urllib.parse import urlencode, urljoin

import httpx
from bs4 import BeautifulSoup

from worker.sources.base import extract_external_id, normalize_html_text
from worker.sources.region_codes import ICETRADE_REGION_MAP, map_regions

BASE_URL = "https://icetrade.by"
URL = f"{BASE_URL}/search/auctions"
USER_AGENT = "belzakupki/0.1 (+https://github.com/mvnby/belzakupki)"
VITEBSK_REGION_ID = "2"
HVAC_VITEBSK_TERMS = (
    "кондиционер",
    "сплит-система",
    "сплит система",
    "вентиляционное оборудование",
)


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
    headers = {"User-Agent": USER_AGENT}
    return headers


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

    with httpx.Client(
        follow_redirects=True,
        headers=build_headers(),
        timeout=10,
        verify=verify,
    ) as client:
        response = client.get(build_search_url(search))
        response.raise_for_status()

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

    with httpx.Client(
        follow_redirects=True,
        headers=build_headers(),
        timeout=10,
        verify=verify,
    ) as client:
        for search in searches:
            remaining = None if limit is None else limit - len(tenders)
            if remaining is not None and remaining <= 0:
                break

            response = client.get(build_search_url(search))
            response.raise_for_status()

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
    headers = build_headers()
    
    with httpx.Client(
        follow_redirects=True,
        headers=headers,
        timeout=15,
        verify=verify,
    ) as client:
        response = client.get(tender_url)
        response.raise_for_status()
        
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

