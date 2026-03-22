"""add full-text search GIN index on trail_routes

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-03-22 18:00:00.000000

"""
from alembic import op

revision = 'a1b2c3d4e5f6'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX ix_trail_routes_fts
        ON trail_routes
        USING gin(
            to_tsvector('russian',
                coalesce(title, '') || ' ' || coalesce(description, '')
            )
        )
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_trail_routes_fts")
