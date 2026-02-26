import uuid
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import TrailRoute, RouteStatus
from app.models.user import Follow, User
from app.schemas.common import PaginatedResponse
from app.schemas.route import RouteResponse
from app.schemas.user import UserProfile
from app.services.route_service import _enrich_routes
from app.services.user_service import _enrich_users


async def get_feed(
    db: AsyncSession,
    user_id: uuid.UUID,
    page: int,
    page_size: int,
) -> PaginatedResponse[RouteResponse]:
    # Subquery: IDs of users I follow
    followed_subq = (
        select(Follow.following_id).where(Follow.follower_id == user_id).scalar_subquery()
    )

    base_filter = and_(
        TrailRoute.author_id.in_(followed_subq),
        TrailRoute.status == RouteStatus.published,
    )

    total_result = await db.execute(
        select(func.count()).select_from(TrailRoute).where(base_filter)
    )
    total = total_result.scalar_one()

    result = await db.execute(
        select(TrailRoute)
        .where(base_filter)
        .order_by(TrailRoute.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    routes = result.scalars().all()

    items = await _enrich_routes(db, list(routes), user_id)
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if total else 0,
    )


async def search_routes(
    db: AsyncSession,
    q: str,
    page: int,
    page_size: int,
    user_id: Optional[uuid.UUID],
) -> PaginatedResponse[RouteResponse]:
    pattern = f"%{q}%"
    base_filter = and_(
        TrailRoute.title.ilike(pattern) | TrailRoute.description.ilike(pattern),
        TrailRoute.status == RouteStatus.published,
    )

    total_result = await db.execute(
        select(func.count()).select_from(TrailRoute).where(base_filter)
    )
    total = total_result.scalar_one()

    result = await db.execute(
        select(TrailRoute)
        .where(base_filter)
        .order_by(TrailRoute.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    routes = result.scalars().all()

    items = await _enrich_routes(db, list(routes), user_id)
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if total else 0,
    )


async def get_regions(db: AsyncSession) -> list[str]:
    result = await db.execute(
        select(TrailRoute.region)
        .where(TrailRoute.region.isnot(None), TrailRoute.status == RouteStatus.published)
        .distinct()
        .order_by(TrailRoute.region)
    )
    return [row for row in result.scalars().all()]


async def search_users(
    db: AsyncSession,
    q: str,
    page: int,
    page_size: int,
    current_user_id: Optional[uuid.UUID],
) -> PaginatedResponse[UserProfile]:
    pattern = f"%{q}%"
    base_filter = User.username.ilike(pattern) | User.display_name.ilike(pattern)

    total_result = await db.execute(
        select(func.count()).select_from(User).where(base_filter)
    )
    total = total_result.scalar_one()

    result = await db.execute(
        select(User)
        .where(base_filter)
        .order_by(User.followers_count.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    users = result.scalars().all()

    items = await _enrich_users(db, list(users), current_user_id)
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if total else 0,
    )
