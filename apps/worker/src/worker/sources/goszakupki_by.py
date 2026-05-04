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

        if len(cols) < 2:
            continue

        number_text = cols[0].get_text("\n", strip=True)
        details_text = cols[1].get_text("\n", strip=True)
        link_tag = cols[1].find("a")

        if not details_text or link_tag is None or not link_tag.get("href"):
            continue

        title = link_tag.get_text(" ", strip=True)
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
    verify = should_verify_ssl() if verify_ssl is None else verify_ssl

    with httpx.Client(
        follow_redirects=True,
        headers=build_headers(),
        timeout=10,
        verify=verify,
    ) as client:
        client.get(BASE_URL).raise_for_status()
        response = client.get(URL)
        response.raise_for_status()

        if response.url.path == "/site/login":
            raise RuntimeError(
                "goszakupki.by redirected to login after session warm-up"
            )

        return parse_tenders_html(response.text, limit=limit)
