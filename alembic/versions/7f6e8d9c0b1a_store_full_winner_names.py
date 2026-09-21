"""store full winner names

Revision ID: 7f6e8d9c0b1a
Revises: 3c1d3f2401c8
Create Date: 2026-09-22 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7f6e8d9c0b1a"
down_revision: Union[str, None] = "3c1d3f2401c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "tender_results",
        "winner_name",
        existing_type=sa.String(length=500),
        type_=sa.Text(),
        postgresql_using="winner_name::text",
    )


def downgrade() -> None:
    op.alter_column(
        "tender_results",
        "winner_name",
        existing_type=sa.Text(),
        type_=sa.String(length=500),
        postgresql_using="winner_name::varchar(500)",
    )
