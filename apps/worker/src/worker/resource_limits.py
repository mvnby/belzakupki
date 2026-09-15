"""Small resource-safety primitives shared by worker processes."""
from __future__ import annotations

import os

from loguru import logger


def positive_int_env(name: str, default: int) -> int:
    """Read a strictly positive integer without making startup fragile."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        logger.warning("{} must be an integer; using default {}", name, default)
        return default
    if value < 1:
        logger.warning("{} must be positive; using default {}", name, default)
        return default
    return value
