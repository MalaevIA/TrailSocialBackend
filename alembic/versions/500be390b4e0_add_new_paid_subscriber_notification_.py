"""add new_paid_subscriber notification type

Revision ID: 500be390b4e0
Revises: b45c4476abc4
Create Date: 2026-03-24 15:41:55.865562

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '500be390b4e0'
down_revision: Union[str, None] = 'b45c4476abc4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'new_paid_subscriber'")


def downgrade() -> None:
    # PostgreSQL не поддерживает удаление значений из enum — downgrade не нужен
    pass
