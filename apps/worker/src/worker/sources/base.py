"""Shared utilities for all procurement source parsers.

Functions and types in this module are used by both goszakupki_by and
icetrade_by — keep this module free of any source-specific logic.
"""
from __future__ import annotations

import re
from hashlib import sha256
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
