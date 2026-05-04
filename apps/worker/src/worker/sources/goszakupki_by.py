from __future__ import annotations

from hashlib import sha256
import os
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://goszakupki.by"
URL = f"{BASE_URL}/tenders/posted"
USER_AGENT = "belzakupki/0.1 (+https://github.com/mvnby/belzakupki)"


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


def parse_tenders_html(
    html: str,
    *,
    limit: int | None = None,
    base_url: str = BASE_URL,
) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    tenders: list[dict] = []

    rows = soup.select("table tbody tr")

    for row in rows:
        cols = row.find_all("td")

        if not cols:
            continue

        title = cols[0].get_text(strip=True)
        link_tag = cols[0].find("a")

        if not title or link_tag is None or not link_tag.get("href"):
            continue

        url = urljoin(base_url, link_tag["href"])

        tenders.append(
            {
                "external_id": extract_external_id(url),
                "title": title,
                "url": url,
                "status": "posted",
            }
        )

        if limit is not None and len(tenders) >= limit:
            break

    return tenders


def fetch_tenders(
    limit: int | None = None,
    *,
    verify_ssl: bool | None = None,
) -> list[dict]:
    response = httpx.get(
        URL,
        follow_redirects=True,
        headers=build_headers(),
        timeout=10,
        verify=should_verify_ssl() if verify_ssl is None else verify_ssl,
    )
    response.raise_for_status()

    if response.url.path == "/site/login":
        raise RuntimeError(
            "goszakupki.by redirected to login; set GOSZAKUPKI_COOKIE "
            "with an authenticated session cookie to fetch posted tenders"
        )

    return parse_tenders_html(response.text, limit=limit)
