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
    """Источник тендеров (например, госзакупки или icetrade).

    Хранит информацию о сайтах-первоисточниках, с которых собираются тендеры.
    """
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
    """Тендер (закупка), импортированный из внешнего источника.

    Содержит сырые метаданные тендера (извлеченные из HTML) и ссылку на источник.
    Связан с совпадениями TenderMatch (один тендер может подходить под несколько профилей).
    """
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
    result: Mapped[TenderResult | None] = relationship(
        back_populates="tender",
        cascade="all, delete-orphan",
        uselist=False,
    )


class SearchProfile(Base, TimestampMixin, ReprMixin):
    """Профиль поиска тендеров.

    Содержит настройки фильтрации: ключевые слова, минус-слова,
    регионы, категории, а также настройки планировщика автозапуска.
    """
    __tablename__ = "search_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    preset_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    niche_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    keywords: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    negative_keywords: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    regions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    categories: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    min_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=0,
    )
    schedule_interval: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    matches: Mapped[list["TenderMatch"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    notification_channels: Mapped[list["NotificationChannel"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
    )


class TenderMatch(Base, TimestampMixin, ReprMixin):
    """Совпадение тендера с поисковым профилем.

    Создается на этапе скоринга, если тендер набрал балл больше min_score в профиле.
    Хранит оценку релевантности (score), причину совпадения (matched_keywords),
    а также результаты детального ИИ-анализа (ai_relevance, ai_analysis).
    """
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

    ai_relevance: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ai_analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    tender: Mapped[Tender] = relationship(back_populates="matches")
    profile: Mapped[SearchProfile] = relationship(back_populates="matches")
    notification_logs: Mapped[list["NotificationLog"]] = relationship(
        back_populates="match",
        cascade="all, delete-orphan",
    )


class NotificationChannel(Base, TimestampMixin, ReprMixin):
    """Канал уведомлений для конкретного профиля поиска.

    Примеры каналов: Telegram-чат (содержит bot_token/chat_id в JSON config).
    Уведомления отправляются, когда для профиля появляется новое совпадение TenderMatch.
    """
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
    """Журнал отправки уведомлений.

    Служит для фиксации факта и статуса отправки уведомления о конкретном совпадении
    (match_id) по конкретному каналу уведомлений (channel_id).
    Предотвращает повторную отправку одного и того же тендера в тот же канал.
    """
    __tablename__ = "notification_logs"
    __table_args__ = (
        UniqueConstraint(
            "match_id",
            "channel_id",
            name="uq_notification_logs_match_id_channel_id",
        ),
    )

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


class TenderResult(Base, TimestampMixin, ReprMixin):
    """Результаты проведения закупки (выбранные победители, цены договоров, список участников)."""
    __tablename__ = "tender_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    tender_id: Mapped[int] = mapped_column(
        ForeignKey("tenders.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    status: Mapped[str] = mapped_column(String(64), nullable=False)
    winner_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    winner_unp: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contract_price: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    raw_result_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    tender: Mapped[Tender] = relationship(back_populates="result")
