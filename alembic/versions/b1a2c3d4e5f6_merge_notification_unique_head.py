"""merge_notification_unique_and_current_head

Revision ID: b1a2c3d4e5f6
Revises: 9768e10fdbc4, dc62d3e5004d
Create Date: 2026-05-23 20:36:00.000000

Merges the unique constraint on notification_logs (branch 9768e10fdbc4)
with the current main head (dc62d3e5004d).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b1a2c3d4e5f6'
down_revision: Union[str, tuple, None] = ('9768e10fdbc4', 'dc62d3e5004d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass  # merge only — no schema changes


def downgrade() -> None:
    pass  # merge only — no schema changes
