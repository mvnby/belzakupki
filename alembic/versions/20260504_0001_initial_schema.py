from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260504_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "search_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "negative_keywords",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_search_profiles")),
    )

    op.create_table(
        "tender_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tender_sources")),
        sa.UniqueConstraint("code", name=op.f("uq_tender_sources_code")),
    )

    op.create_table(
        "notification_channels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["search_profiles.id"],
            name=op.f("fk_notification_channels_profile_id_search_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_channels")),
    )

    op.create_table(
        "tenders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=1000), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("customer_name", sa.String(length=500), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["tender_sources.id"],
            name=op.f("fk_tenders_source_id_tender_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenders")),
        sa.UniqueConstraint(
            "source_id",
            "external_id",
            name="uq_tenders_source_id_external_id",
        ),
    )
    op.create_index("ix_tenders_content_hash", "tenders", ["content_hash"])
    op.create_index("ix_tenders_deadline_at", "tenders", ["deadline_at"])
    op.create_index("ix_tenders_published_at", "tenders", ["published_at"])
    op.create_index("ix_tenders_status", "tenders", ["status"])

    op.create_table(
        "tender_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tender_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column(
            "matched_keywords",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["search_profiles.id"],
            name=op.f("fk_tender_matches_profile_id_search_profiles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tender_id"],
            ["tenders.id"],
            name=op.f("fk_tender_matches_tender_id_tenders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tender_matches")),
        sa.UniqueConstraint(
            "tender_id",
            "profile_id",
            name="uq_tender_matches_tender_id_profile_id",
        ),
    )
    op.create_index("ix_tender_matches_score", "tender_matches", ["score"])
    op.create_index("ix_tender_matches_status", "tender_matches", ["status"])

    op.create_table(
        "notification_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["notification_channels.id"],
            name=op.f("fk_notification_logs_channel_id_notification_channels"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["tender_matches.id"],
            name=op.f("fk_notification_logs_match_id_tender_matches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_logs")),
    )


def downgrade() -> None:
    op.drop_table("notification_logs")
    op.drop_index("ix_tender_matches_status", table_name="tender_matches")
    op.drop_index("ix_tender_matches_score", table_name="tender_matches")
    op.drop_table("tender_matches")
    op.drop_index("ix_tenders_status", table_name="tenders")
    op.drop_index("ix_tenders_published_at", table_name="tenders")
    op.drop_index("ix_tenders_deadline_at", table_name="tenders")
    op.drop_index("ix_tenders_content_hash", table_name="tenders")
    op.drop_table("tenders")
    op.drop_table("notification_channels")
    op.drop_table("tender_sources")
    op.drop_table("search_profiles")
