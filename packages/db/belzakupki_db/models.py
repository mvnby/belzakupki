from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from belzakupki_db.base import Base, ReprMixin, TimestampMixin


class TenderSource(Base, TimestampMixin, ReprMixin):
    __tablename__ = "tender_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    tenders: Mapped[list["Tender"]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
    )


class Tender(Base, TimestampMixin, ReprMixin):
    __tablename__ = "tenders"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "external_id",
            name="uq_tenders_source_id_external_id",
        ),
        Index("ix_tenders_content_hash", "content_hash"),
        Index("ix_tenders_published_at", "published_at"),
        Index("ix_tenders_deadline_at", "deadline_at"),
        Index("ix_tenders_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    source_id: Mapped[int] = mapped_column(
        ForeignKey("tender_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(500), nullable=True)

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="posted")

    raw_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)

    source: Mapped[TenderSource] = relationship(back_populates="tenders")
    matches: Mapped[list["TenderMatch"]] = relationship(
        back_populates="tender",
        cascade="all, delete-orphan",
    )


class SearchProfile(Base, TimestampMixin, ReprMixin):
    __tablename__ = "search_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    keywords: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    negative_keywords: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    matches: Mapped[list["TenderMatch"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    notification_channels: Mapped[list["NotificationChannel"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
    )


class TenderMatch(Base, TimestampMixin, ReprMixin):
    __tablename__ = "tender_matches"
    __table_args__ = (
        UniqueConstraint(
            "tender_id",
            "profile_id",
            name="uq_tender_matches_tender_id_profile_id",
        ),
        Index("ix_tender_matches_score", "score"),
        Index("ix_tender_matches_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    tender_id: Mapped[int] = mapped_column(
        ForeignKey("tenders.id", ondelete="CASCADE"),
        nullable=False,
    )
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("search_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )

    score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=0,
    )
    matched_keywords: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="new")

    tender: Mapped[Tender] = relationship(back_populates="matches")
    profile: Mapped[SearchProfile] = relationship(back_populates="matches")
    notification_logs: Mapped[list["NotificationLog"]] = relationship(
        back_populates="match",
        cascade="all, delete-orphan",
    )


class NotificationChannel(Base, TimestampMixin, ReprMixin):
    __tablename__ = "notification_channels"

    id: Mapped[int] = mapped_column(primary_key=True)

    profile_id: Mapped[int] = mapped_column(
        ForeignKey("search_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )

    type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    profile: Mapped[SearchProfile] = relationship(
        back_populates="notification_channels",
    )
    notification_logs: Mapped[list["NotificationLog"]] = relationship(
        back_populates="channel",
        cascade="all, delete-orphan",
    )


class NotificationLog(Base, ReprMixin):
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(primary_key=True)

    match_id: Mapped[int] = mapped_column(
        ForeignKey("tender_matches.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("notification_channels.id", ondelete="CASCADE"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    match: Mapped[TenderMatch] = relationship(back_populates="notification_logs")
    channel: Mapped[NotificationChannel] = relationship(
        back_populates="notification_logs",
    )
