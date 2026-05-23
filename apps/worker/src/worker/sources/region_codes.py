"""Canonical region codes and per-source mappings for Belarus procurement portals.

Canonical codes (used in SearchProfile.regions):
    '1' = Brest region
    '2' = Vitebsk region
    '3' = Gomel region
    '4' = Grodno region
    '5' = Minsk City
    '6' = Minsk region
    '7' = Mogilev region

Each portal uses its own numeric scheme — this module holds the single
source of truth for all mappings so they can be updated in one place.
"""
from __future__ import annotations

# Canonical → goszakupki.by region ID
GOSZAKUPKI_REGION_MAP: dict[str, str] = {
    "1": "1",  # Brest
    "2": "2",  # Vitebsk
    "3": "3",  # Gomel
    "4": "4",  # Grodno
    "5": "7",  # Minsk City  (goszakupki uses 7)
    "6": "5",  # Minsk region (goszakupki uses 5)
    "7": "6",  # Mogilev     (goszakupki uses 6)
}

# Canonical → icetrade.by region ID
ICETRADE_REGION_MAP: dict[str, str] = {
    "1": "1",  # Brest
    "2": "2",  # Vitebsk
    "3": "3",  # Gomel
    "4": "4",  # Grodno
    "5": "7",  # Minsk City  (icetrade uses 7)
    "6": "6",  # Minsk region (icetrade uses 6)
    "7": "5",  # Mogilev     (icetrade uses 5)
}


def map_regions(canonical_codes: list[str], mapping: dict[str, str]) -> list[str]:
    """Convert a list of canonical region codes to portal-specific codes.

    Unknown codes are passed through unchanged so they don't silently disappear.
    """
    return [mapping.get(code, code) for code in canonical_codes]
