"""Structured Goszakupki lot rows and their attached conditions."""

import re

from bs4 import BeautifulSoup, Tag

from worker.sources.base import normalize_html_text

_NUMBER = re.compile(r"(?:№\s*)?([1-9]\d*)")
_PRICE = re.compile(r",\s+(\d[\d\s.,]*\s+[A-Z]{3})$")
_FIELDS = {
    "delivery_place": re.compile(r"^место(?:\s*\(места\))?\s+(?:поставк|выполнени|оказани)"),
    "delivery_period": re.compile(r"^срок(?:\s*\(сроки\))?\s+(?:поставк|выполнени|оказани)"),
    "okrb": re.compile(r"\bокрб\b"),
}


def _text(element: Tag | None) -> str:
    return normalize_html_text(element.get_text(" ", strip=True)) if element is not None else ""


def _lot_conditions(row: Tag | None) -> dict[str, str]:
    if row is None:
        return {}
    values = {}
    for value in row.select("span.col-md-6"):
        label = _text(value.find_previous_sibling()).casefold().strip(": ")
        content = _text(value)
        for field, pattern in _FIELDS.items():
            if content and pattern.search(label):
                values.setdefault(field, content)
    return values


def native_lots(soup: BeautifulSoup) -> tuple[list[dict[str, str]], bool] | None:
    """Return identified native lots, or None for the legacy table format."""
    table = soup.select_one("table#lotsList")
    if table is None:
        return None
    lots: dict[str, dict[str, str]] = {}
    duplicates = set()
    observed = 0
    for row in table.select("tr.lot-row"):
        if row.find_parent("table") is not table:
            continue
        observed += 1
        number = _NUMBER.fullmatch(_text(row.select_one(".lot-num")))
        title = _text(row.select_one(".lot-description"))
        if number is None or not title:
            continue
        key = number[1]
        if key in lots:
            duplicates.add(key)
            continue
        combined = _text(row.select_one("td.lot-count-price"))
        match = _PRICE.search(combined)
        quantity, price = (combined[:match.start()].strip(), match[1]) if match else (combined, "")
        conditions = _lot_conditions(table.find("tr", id=f"lot-inf-{key}", class_="lot-inf"))
        lots[key] = {
            "number": key, "name": title, "quantity": quantity, "estimated_value": price,
            "status": _text(row.select_one("td.lot-status")),
            "okrb": conditions.get("okrb", ""),
            "delivery_place": conditions.get("delivery_place", ""),
            "delivery_period": conditions.get("delivery_period", ""),
        }
    verified = [lot for key, lot in lots.items() if key not in duplicates]
    return verified, bool(verified) and len(verified) == observed
