"""Exact procurement references; never infer identity from titles or documents."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from loguru import logger


GOSZAKUPKI_KINDS = "marketing|etrade|request|single-source|single-source-reference|limited"


def normalize_procurement_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if re.search(r"[\x00-\x1f\x7f]", value):
        return None
    value = value.strip()
    if not value or re.search(r"[\s\\\x00-\x1f\x7f]", value):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or parsed.username is not None
                or parsed.password is not None
                or parsed.port not in {None, 80 if parsed.scheme == "http" else 443}):
            return None
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host == "goszakupki.by":
        match = re.fullmatch(rf"/({GOSZAKUPKI_KINDS})/view/([1-9][0-9]*)/?", parsed.path)
        if match:
            return f"https://{host}/{match[1]}/view/{match[2]}"
    elif host == "icetrade.by":
        match = re.fullmatch(r"/tenders/all/view/([1-9][0-9]*)/?", parsed.path)
        if match:
            return f"https://{host}/tenders/all/view/{match[1]}"
    elif host == "zakupki.butb.by" and parsed.path == "/auctions/viewinvitation.html":
        auctions = parse_qs(parsed.query, keep_blank_values=True).get("auction", [])
        if len(auctions) == 1 and re.fullmatch(r"[A-Za-z0-9_-]+", auctions[0]):
            return f"https://{host}/auctions/viewinvitation.html?auction={auctions[0]}"
    return None


def explicit_reference(source: str, raw: dict[str, Any]) -> tuple[bool, str | None]:
    """Only documented current-procedure fields count as an explicit reference."""
    if source == "gias_by":
        provider = raw.get("raw_data")
        if isinstance(provider, dict):
            value = provider.get("auctionUrl")
            # Search-only fallback can explicitly contain null/empty fields.
            # That is absence of detail, not evidence contradicting a URL.
            if value is not None and (not isinstance(value, str) or value.strip()):
                return True, normalize_procurement_url(value)
    if source in {"gias_by", "icetrade_by"} and "canonical_url" in raw:
        return True, normalize_procurement_url(raw["canonical_url"])
    return False, None


def tender_canonical_url(source: str, url: str, raw: dict[str, Any]) -> str | None:
    if raw.get("canonical_reference_conflict"):
        return None
    present, reference = explicit_reference(source, raw)
    if present:
        # A persisted value and a fresh structured reference must agree.
        if "canonical_url" in raw and normalize_procurement_url(raw["canonical_url"]) != reference:
            return None
        return reference
    native_hosts = {
        "goszakupki_by": "goszakupki.by", "icetrade_by": "icetrade.by",
        "butb_by": "zakupki.butb.by",
    }
    normalized = normalize_procurement_url(url)
    if normalized and urlsplit(normalized).hostname == native_hosts.get(source):
        return normalized
    return None


def preserve_canonical_reference(
    source: str, incoming: dict[str, Any], previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Retain verified enrichment across listing refreshes; contradictions fail closed."""
    result = dict(incoming)
    previous = previous or {}
    if result.get("canonical_reference_conflict"):
        result["canonical_url"] = None
        return result
    if previous.get("canonical_reference_conflict"):
        result.update(canonical_url=None, canonical_reference_conflict=previous["canonical_reference_conflict"])
        return result
    fresh_present, fresh = explicit_reference(source, result)
    old_present, old = explicit_reference(source, previous)
    # Invalid newer evidence suppresses export but must not erase the earlier
    # verified URL: otherwise A -> invalid -> B silently switches identity.
    verified = normalize_procurement_url(previous.get("canonical_reference_verified")) or old
    if verified:
        result["canonical_reference_verified"] = verified
    if fresh_present:
        result["canonical_url"] = fresh
        if verified and fresh and verified != fresh:
            result.update(canonical_url=None, canonical_reference_conflict=[verified, fresh])
            logger.warning("Conflicting procurement references for {}: {} / {}", source, verified, fresh)
        elif fresh:
            result["canonical_reference_verified"] = fresh
    elif old_present:
        result["canonical_url"] = old
    return result
