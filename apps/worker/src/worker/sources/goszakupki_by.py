from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
import os
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

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

    @property
    def label(self) -> str:
        parts: list[str] = []

        if self.text:
            parts.append(f"text={self.text}")

        if self.regions:
            parts.append("regions=" + ",".join(self.regions))

        if self.industry:
            parts.append(f"industry={self.industry}")

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
        params.append(("TendersSearch[region][]", region))

    if search.industry:
        params.append(("TendersSearch[industry]", search.industry))

    return params


def build_search_url(search: GoszakupkiSearch | None) -> str:
    params = build_search_params(search)

    if not params:
        return URL

    return f"{URL}?{urlencode(params)}"


def normalize_html_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


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
