"""add user preferences (city_ids, interest_ids, fitness_level)

Revision ID: f1a2b3c4d5e6
Revises: d4e5f6a7b8c9
Create Date: 2026-03-22 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

revision = 'f1a2b3c4d5e6'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column(
        'fitness_level', sa.String(20), nullable=True
    ))
    op.add_column('users', sa.Column(
        'city_ids', ARRAY(sa.String()), nullable=False, server_default='{}'
    ))
    op.add_column('users', sa.Column(
        'interest_ids', ARRAY(sa.String()), nullable=False, server_default='{}'
    ))


def downgrade() -> None:
    op.drop_column('users', 'interest_ids')
    op.drop_column('users', 'city_ids')
    op.drop_column('users', 'fitness_level')
