"""add_unique_notification_log

Revision ID: 9768e10fdbc4
Revises: 6ee65bf29f66
Create Date: 2026-05-23 20:04:32.000000

Adds a unique constraint on notification_logs(match_id, channel_id)
to prevent duplicate notifications when dispatch_notifications() is
called multiple times for the same match.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9768e10fdbc4'
down_revision: Union[str, None] = '6ee65bf29f66'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: remove duplicate notification_logs keeping the latest row per (match_id, channel_id)
    op.execute("""
        DELETE FROM notification_logs
        WHERE id NOT IN (
            SELECT MAX(id)
            FROM notification_logs
            GROUP BY match_id, channel_id
        )
    """)

    # Step 2: now it's safe to add the unique constraint
    op.create_unique_constraint(
        'uq_notification_logs_match_id_channel_id',
        'notification_logs',
        ['match_id', 'channel_id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'uq_notification_logs_match_id_channel_id',
        'notification_logs',
        type_='unique',
    )
