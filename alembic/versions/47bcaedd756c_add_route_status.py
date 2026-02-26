"""add route status

Revision ID: 47bcaedd756c
Revises: 4db9b41c68ea
Create Date: 2026-02-26 20:14:24.057708

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '47bcaedd756c'
down_revision: Union[str, None] = '4db9b41c68ea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    routestatus = sa.Enum('draft', 'private', 'published', name='routestatus')
    routestatus.create(op.get_bind(), checkfirst=True)
    op.add_column('trail_routes', sa.Column('status', routestatus, nullable=False, server_default='published'))
    op.create_index(op.f('ix_trail_routes_status'), 'trail_routes', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_trail_routes_status'), table_name='trail_routes')
    op.drop_column('trail_routes', 'status')
    sa.Enum(name='routestatus').drop(op.get_bind(), checkfirst=True)
