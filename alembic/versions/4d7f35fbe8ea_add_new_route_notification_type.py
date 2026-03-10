"""add new_route notification type

Revision ID: 4d7f35fbe8ea
Revises: 4f40e2bfc523
Create Date: 2026-03-11 01:12:17.570398

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '4d7f35fbe8ea'
down_revision: Union[str, None] = '4f40e2bfc523'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'new_route'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; rename requires recreating the type.
    pass
