"""add check constraints on counters

Revision ID: d4e5f6a7b8c9
Revises: c7e8f9a0b1d2
Create Date: 2026-03-22 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c7e8f9a0b1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint("ck_users_followers_count_non_negative", "users", "followers_count >= 0")
    op.create_check_constraint("ck_users_following_count_non_negative", "users", "following_count >= 0")
    op.create_check_constraint("ck_users_routes_count_non_negative", "users", "routes_count >= 0")
    op.create_check_constraint("ck_trail_routes_likes_count_non_negative", "trail_routes", "likes_count >= 0")
    op.create_check_constraint("ck_trail_routes_saves_count_non_negative", "trail_routes", "saves_count >= 0")
    op.create_check_constraint("ck_trail_routes_comments_count_non_negative", "trail_routes", "comments_count >= 0")
    op.create_check_constraint("ck_comments_likes_count_non_negative", "comments", "likes_count >= 0")


def downgrade() -> None:
    op.drop_constraint("ck_comments_likes_count_non_negative", "comments")
    op.drop_constraint("ck_trail_routes_comments_count_non_negative", "trail_routes")
    op.drop_constraint("ck_trail_routes_saves_count_non_negative", "trail_routes")
    op.drop_constraint("ck_trail_routes_likes_count_non_negative", "trail_routes")
    op.drop_constraint("ck_users_routes_count_non_negative", "users")
    op.drop_constraint("ck_users_following_count_non_negative", "users")
    op.drop_constraint("ck_users_followers_count_non_negative", "users")
