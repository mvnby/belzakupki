"""Morphological scoring for Russian-language procurement tenders.

Uses pymorphy3 to normalise words to their lemma (base form) before
keyword matching, so "кондиционер" matches "кондиционеров",
"кондиционировании" etc.

pymorphy3 is loaded lazily: if the package is not installed the module
gracefully falls back to the plain substring matching from scoring.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from loguru import logger


# ---------------------------------------------------------------------------
# Lazy analyser — instantiated once, reused across calls
# ---------------------------------------------------------------------------

_morph: Any = None
_morph_available: bool | None = None   # None = not yet checked


def _get_morph() -> Any | None:
    global _morph, _morph_available

    if _morph_available is False:
        return None
    if _morph is not None:
        return _morph

    try:
        import pymorphy3  # type: ignore[import]
        _morph = pymorphy3.MorphAnalyzer()
        _morph_available = True
        logger.info("pymorphy3 MorphAnalyzer initialised successfully.")
        return _morph
    except ImportError:
        _morph_available = False
        logger.warning(
            "pymorphy3 is not installed — falling back to plain substring matching. "
            "Run `pip install pymorphy3` to enable morphological analysis."
        )
        return None


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

_SPACE_RE = re.compile(r"\s+")


def _lemmatise_word(word: str, morph: Any) -> str:
    """Return the normal form (lemma) of a single Russian word."""
    parses = morph.parse(word)
    if not parses:
        return word
    return parses[0].normal_form


def normalise_for_matching(text: str) -> str:
    """Lowercase, collapse whitespace, and optionally lemmatise every word."""
    if not text:
        return ""

    lowered = _SPACE_RE.sub(" ", text.casefold()).strip()
    morph = _get_morph()
    if morph is None:
        return lowered

    words = lowered.split()
    return " ".join(_lemmatise_word(w, morph) for w in words)


# ---------------------------------------------------------------------------
# Public helper used by scoring.py
# ---------------------------------------------------------------------------

def build_normalised_keyword(keyword: str) -> str:
    """Normalise a single keyword phrase for matching."""
    return normalise_for_matching(keyword)
