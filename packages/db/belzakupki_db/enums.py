"""Shared status enums for the belzakupki domain.

Using ``str`` mixin so that values serialise to plain strings both in
SQLAlchemy (stored as VARCHAR) and in JSON API responses — no extra
configuration required in either layer.
"""
from __future__ import annotations

import enum


class MatchStatus(str, enum.Enum):
    """Lifecycle statuses for a TenderMatch record."""

    NEW = "new"
    PROCESSED = "processed"
    REJECTED_BY_AI = "rejected_by_ai"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    IN_WORK = "in_work"
    PROPOSAL_SENT = "proposal_sent"
    WON = "won"
    LOST = "lost"


class NotificationStatus(str, enum.Enum):
    """Lifecycle statuses for a NotificationLog record."""

    PENDING = "pending"
    SENT = "sent"
    ERROR = "error"
