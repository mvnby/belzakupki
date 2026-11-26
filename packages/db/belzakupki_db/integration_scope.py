"""Configuration shared by the public feed and collector workers."""

import os


def integration_profile_ids(name: str) -> tuple[int, ...]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return ()
    values = tuple(sorted({int(value.strip()) for value in raw.split(",")}))
    if any(value <= 0 for value in values):
        raise ValueError(f"Invalid profile identifiers in {name}")
    return values


def market_profile_ids() -> tuple[int, ...]:
    market = integration_profile_ids("INTEGRATION_MARKET_PROFILE_IDS")
    if market and set(market).intersection(integration_profile_ids("INTEGRATION_PROFILE_IDS")):
        raise ValueError("Market and CRM integration profiles must be distinct")
    return market


def isolated_market_profile_ids() -> tuple[int, ...]:
    try:
        return market_profile_ids()
    except ValueError:
        # The public API rejects misconfiguration. Keep the existing CRM
        # pipeline operating if a second, invalid scope has been entered.
        return ()
