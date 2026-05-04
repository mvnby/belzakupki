from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

URL = "https://goszakupki.by/tenders/posted"


def fetch_tenders() -> list[dict]:
    response = httpx.get(URL, timeout=10)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")

    tenders: list[dict] = []

    rows = soup.select("table tbody tr")

    for row in rows:
        cols = row.find_all("td")
        if not cols:
            continue

        title = cols[0].get_text(strip=True)
        link_tag = cols[0].find("a")
        url = link_tag["href"] if link_tag else None

        tenders.append(
            {
                "title": title,
                "url": url,
            }
        )

    return tenders
