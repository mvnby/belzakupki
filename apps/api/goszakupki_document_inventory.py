"""Bounded read-through cache for exact Goszakupki lot and attachment listings."""

import logging
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass
from threading import Lock
from time import monotonic

from bs4 import BeautifulSoup

from worker.sources.goszakupki_by import attachments_from_page, fetch_tender_html
from worker.sources.goszakupki_lots import native_lots

MAX_DOCUMENTS = 100
MAX_DOCUMENT_NAME = 500
MAX_DOCUMENT_URL = 2048
MAX_LOTS = 100
_MAX_ENTRIES = 128
_MAX_PARALLEL_READS = 2
_PAGE_BYTES = 2 * 1024 * 1024
_TIMEOUT_SECONDS = 3
_CACHE_SECONDS = 10 * 60
_FAILURE_RETRY_SECONDS = 20

@dataclass(frozen=True)
class PublicInventory:
    attachments: tuple[dict[str, str], ...]
    complete: bool
    lots: tuple[dict[str, str], ...]
    lots_complete: bool


_cache: OrderedDict[str, tuple[float, PublicInventory | None]] = OrderedDict()
_pending: dict[str, Future[PublicInventory | None]] = {}
_lock = Lock()
logger = logging.getLogger(__name__)


def refresh_inventory(canonical_url: str) -> PublicInventory | None:
    with _lock:
        cached = _cache.get(canonical_url)
        if cached and cached[0] > monotonic():
            _cache.move_to_end(canonical_url)
            return cached[1]
        _cache.pop(canonical_url, None)
        pending = _pending.get(canonical_url)
        leader = pending is None
        if leader:
            if len(_pending) >= _MAX_PARALLEL_READS:
                return None
            pending = _pending[canonical_url] = Future()
    if not leader:
        try:
            return pending.result(timeout=2 * _TIMEOUT_SECONDS)
        except TimeoutError:
            return None

    result = None
    try:
        html = fetch_tender_html(canonical_url, timeout=_TIMEOUT_SECONDS, max_page_bytes=_PAGE_BYTES)
        page = BeautifulSoup(html, "html.parser")
        attachments = attachments_from_page(page, canonical_url)
        bounded = tuple(attachment for attachment in attachments[:MAX_DOCUMENTS]
                        if len(attachment["name"]) <= MAX_DOCUMENT_NAME and len(attachment["url"]) <= MAX_DOCUMENT_URL)
        lots, lots_complete = native_lots(page) or ([], False)
        bounded_lots = tuple({key: value[:1000] for key, value in lot.items()} for lot in lots[:MAX_LOTS])
        result = PublicInventory(
            bounded, complete=bool(bounded) and len(bounded) == len(attachments),
            lots=bounded_lots, lots_complete=lots_complete and list(bounded_lots) == lots,
        )
    except Exception as error:
        logger.warning("Goszakupki document inventory unavailable: %s", type(error).__name__)
    finally:
        expires = monotonic() + (_CACHE_SECONDS if result and (result.attachments or result.lots) else _FAILURE_RETRY_SECONDS)
        with _lock:
            _cache[canonical_url] = (expires, result)
            if len(_cache) > _MAX_ENTRIES:
                _cache.popitem(last=False)
            _pending.pop(canonical_url).set_result(result)
    return result
