"""add notification retry state

Revision ID: a8080519ec64
Revises: 7f6e8d9c0b1a
Create Date: 2026-11-07 00:50:20.622646

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8080519ec64'
down_revision: Union[str, None] = '7f6e8d9c0b1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('notification_logs', sa.Column('attempt_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('notification_logs', sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('notification_logs', 'next_attempt_at')
    op.drop_column('notification_logs', 'attempt_count')
