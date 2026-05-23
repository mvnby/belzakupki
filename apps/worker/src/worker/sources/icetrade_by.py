from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
import os
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

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


def extract_external_id(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    for key in ("id", "tender_id", "number"):
        values = query.get(key)
        if values:
            return values[0]

    path_key = parsed.path.rstrip("/").split("/")[-1]

    if path_key:
        return path_key[:128]

    return sha256(url.encode("utf-8")).hexdigest()


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
            # Map canonical region code to icetrade code
            # Canonical: '1'=Brest, '2'=Vitebsk, '3'=Gomel, '4'=Grodno, '5'=Minsk City, '6'=Minsk Region, '7'=Mogilev
            # Icetrade: '1'=Brest, '2'=Vitebsk, '3'=Gomel, '4'=Grodno, '5'=Mogilev, '6'=Minsk Region, '7'=Minsk City
            mapped_region = region
            if region == '5':
                mapped_region = '7'
            elif region == '6':
                mapped_region = '6'
            elif region == '7':
                mapped_region = '5'
            params.append((f"r[{mapped_region}]", mapped_region))
    else:
        # Если поиск не задан, ищем по всем регионам
        for r in range(1, 8):
            params.append((f"r[{r}]", str(r)))

    return params


def build_search_url(search: IcetradeSearch | None) -> str:
    params = build_search_params(search)
    return f"{URL}?{urlencode(params)}"


def normalize_html_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


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
