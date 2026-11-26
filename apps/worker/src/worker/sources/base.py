"""Shared utilities for all procurement source parsers.

Functions and types in this module are used by both goszakupki_by and
icetrade_by — keep this module free of any source-specific logic.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from itertools import chain, zip_longest
from urllib.parse import parse_qs, urlparse


def extract_external_id(url: str) -> str:
    """Extract a stable external ID from a tender URL.

    Tries common query-param keys first, then falls back to the last
    path segment, and finally to a SHA-256 hash of the full URL.
    """
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


def normalize_html_text(value: str) -> str:
    """Collapse whitespace in HTML-extracted text."""
    return re.sub(r"\s+", " ", value).strip()


def parse_deadline_string(deadline_str: str | None, *, require_time: bool = False) -> datetime | None:
    """Read a Minsk deadline, using the calendar-day cutoff for date-only inputs."""
    match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2})(?::(\d{2}))?)?", deadline_str or "")
    if not match:
        return None
    day, month, year, hour, minute, second = match.groups()
    if require_time and hour is None:
        return None
    try:
        minsk = timezone(timedelta(hours=3))
        return datetime(
            int(year), int(month), int(day), int(hour or 23), int(minute or 59), int(second or 0), tzinfo=minsk,
        ).astimezone(timezone.utc)
    except ValueError:
        return None


def select_search_results(pages: Iterable[list[dict]], limit: int | None, *, balanced: bool) -> list[dict]:
    """Select unique notices, giving each search a turn in a market scan."""
    if limit is not None and limit <= 0:
        return []
    candidates = chain.from_iterable(zip_longest(*pages) if balanced else pages)
    selected = []
    seen = set()
    for notice in candidates:
        if notice is None or notice["external_id"] in seen:
            continue
        seen.add(notice["external_id"])
        selected.append(notice)
        if limit is not None and len(selected) >= limit:
            break
    return selected
