import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select, update, func, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.dialects.postgresql import array as pg_array

from sqlalchemy import and_, or_

from app.models.route import TrailRoute, RouteLike, RouteSave, Difficulty, RouteStatus
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.route import RouteCreate, RouteUpdate, RouteResponse, SortOrder


async def _enrich_routes(
    db: AsyncSession,
    routes: list[TrailRoute],
    user_id: uuid.UUID | None,
) -> list[RouteResponse]:
    if not routes:
        return []

    route_ids = [r.id for r in routes]

    # Bulk fetch authors
    author_ids = list({r.author_id for r in routes})
    result = await db.execute(select(User).where(User.id.in_(author_ids)))
    authors = {u.id: u for u in result.scalars().all()}

    liked_set: set[uuid.UUID] = set()
    saved_set: set[uuid.UUID] = set()

    if user_id:
        result = await db.execute(
            select(RouteLike.route_id).where(
                RouteLike.user_id == user_id,
                RouteLike.route_id.in_(route_ids),
            )
        )
        liked_set = {row for row in result.scalars().all()}

        result = await db.execute(
            select(RouteSave.route_id).where(
                RouteSave.user_id == user_id,
                RouteSave.route_id.in_(route_ids),
            )
        )
        saved_set = {row for row in result.scalars().all()}

    enriched = []
    for route in routes:
        data = RouteResponse.model_validate(route)
        data.author = authors[route.author_id]
        data.is_liked = route.id in liked_set
        data.is_saved = route.id in saved_set
        enriched.append(data)

    return enriched


async def list_routes(
    db: AsyncSession,
    page: int,
    page_size: int,
    region: Optional[str],
    difficulty: Optional[Difficulty],
    user_id: Optional[uuid.UUID],
    author_id: Optional[uuid.UUID] = None,
    sort: SortOrder = SortOrder.recent,
    tags: Optional[list[str]] = None,
    distance_min: Optional[float] = None,
    distance_max: Optional[float] = None,
) -> PaginatedResponse[RouteResponse]:
    query = select(TrailRoute)
    count_query = select(func.count()).select_from(TrailRoute)

    # Видимость: чужие — только published, свои — все (если author_id == user_id)
    if author_id and user_id and author_id == user_id:
        # Автор смотрит свои маршруты — показываем все статусы
        visibility = TrailRoute.author_id == author_id
    elif author_id:
        # Смотрим чужой профиль — только published
        visibility = and_(TrailRoute.author_id == author_id, TrailRoute.status == RouteStatus.published)
    else:
        # Общий список — только published
        visibility = TrailRoute.status == RouteStatus.published

    filters = [visibility]
    if region:
        filters.append(TrailRoute.region == region)
    if difficulty:
        filters.append(TrailRoute.difficulty == difficulty)
    if tags:
        filters.append(
            TrailRoute.tags.isnot(None) & TrailRoute.tags.op("&&")(pg_array(tags))
        )
    if distance_min is not None:
        filters.append(TrailRoute.distance_km >= distance_min)
    if distance_max is not None:
        filters.append(TrailRoute.distance_km <= distance_max)

    query = query.where(and_(*filters))
    count_query = count_query.where(and_(*filters))

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    order = {
        SortOrder.recent: TrailRoute.created_at.desc(),
        SortOrder.popular: TrailRoute.likes_count.desc(),
        SortOrder.distance: TrailRoute.distance_km.asc(),
    }[sort]

    query = query.order_by(order).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    routes = result.scalars().all()

    items = await _enrich_routes(db, list(routes), user_id)
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if total else 0,
    )


def _prepare_route_data(data) -> dict:
    """Сериализует Pydantic-модели (geometry, waypoints) в JSON-совместимый формат."""
    dumped = data.model_dump(exclude_none=True)
    if "geometry" in dumped and dumped["geometry"] is not None:
        dumped["geometry"] = dumped["geometry"]  # уже dict из model_dump
    if "waypoints" in dumped and dumped["waypoints"] is not None:
        dumped["waypoints"] = dumped["waypoints"]  # уже list[dict]
    return dumped


async def create_route(
    db: AsyncSession,
    user_id: uuid.UUID,
    data: RouteCreate,
) -> RouteResponse:
    route = TrailRoute(author_id=user_id, **_prepare_route_data(data))
    db.add(route)

    # Increment user routes_count
    await db.execute(
        update(User).where(User.id == user_id).values(routes_count=User.routes_count + 1)
    )
    await db.flush()

    # Notify followers if published
    if route.status == RouteStatus.published:
        from app.services.notification_service import notify_followers_new_route
        await notify_followers_new_route(db, user_id, route.id)

    # Reload with author
    result = await db.execute(select(TrailRoute).where(TrailRoute.id == route.id))
    route = result.scalar_one()
    items = await _enrich_routes(db, [route], user_id)
    return items[0]


async def get_route(
    db: AsyncSession,
    route_id: uuid.UUID,
    user_id: Optional[uuid.UUID],
) -> RouteResponse:
    result = await db.execute(select(TrailRoute).where(TrailRoute.id == route_id))
    route = result.scalar_one_or_none()
    if not route:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
    # Не-published маршрут виден только автору
    if route.status != RouteStatus.published and route.author_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")

    items = await _enrich_routes(db, [route], user_id)
    return items[0]


async def update_route(
    db: AsyncSession,
    route_id: uuid.UUID,
    user_id: uuid.UUID,
    data: RouteUpdate,
) -> RouteResponse:
    result = await db.execute(select(TrailRoute).where(TrailRoute.id == route_id))
    route = result.scalar_one_or_none()
    if not route:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
    if route.author_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the author")

    old_status = route.status
    update_data = data.model_dump(exclude_none=True)
    update_data["updated_at"] = datetime.now(timezone.utc)
    await db.execute(update(TrailRoute).where(TrailRoute.id == route_id).values(**update_data))
    await db.flush()

    # Notify followers when status changes to published
    new_status = data.status
    if new_status == RouteStatus.published and old_status != RouteStatus.published:
        from app.services.notification_service import notify_followers_new_route
        await notify_followers_new_route(db, user_id, route_id)

    result = await db.execute(select(TrailRoute).where(TrailRoute.id == route_id))
    route = result.scalar_one()
    items = await _enrich_routes(db, [route], user_id)
    return items[0]


async def delete_route(
    db: AsyncSession,
    route_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    result = await db.execute(select(TrailRoute).where(TrailRoute.id == route_id))
    route = result.scalar_one_or_none()
    if not route:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
    if route.author_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the author")

    await db.delete(route)
    await db.execute(
        update(User).where(User.id == user_id).values(routes_count=User.routes_count - 1)
    )
    await db.flush()


async def like_route(db: AsyncSession, route_id: uuid.UUID, user_id: uuid.UUID) -> None:
    from app.models.notification import NotificationType
    from app.services.notification_service import create_notification

    result = await db.execute(select(TrailRoute).where(TrailRoute.id == route_id))
    route = result.scalar_one_or_none()
    if not route:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")

    result = await db.execute(
        select(RouteLike).where(RouteLike.user_id == user_id, RouteLike.route_id == route_id)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already liked")

    db.add(RouteLike(user_id=user_id, route_id=route_id))
    await db.execute(
        update(TrailRoute)
        .where(TrailRoute.id == route_id)
        .values(likes_count=TrailRoute.likes_count + 1)
    )
    await create_notification(
        db,
        recipient_id=route.author_id,
        actor_id=user_id,
        type=NotificationType.route_like,
        route_id=route_id,
    )
    await db.flush()


async def unlike_route(db: AsyncSession, route_id: uuid.UUID, user_id: uuid.UUID) -> None:
    result = await db.execute(
        select(RouteLike).where(RouteLike.user_id == user_id, RouteLike.route_id == route_id)
    )
    like = result.scalar_one_or_none()
    if not like:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Like not found")

    await db.delete(like)
    await db.execute(
        update(TrailRoute)
        .where(TrailRoute.id == route_id)
        .values(likes_count=TrailRoute.likes_count - 1)
    )
    await db.flush()


async def save_route(db: AsyncSession, route_id: uuid.UUID, user_id: uuid.UUID) -> None:
    result = await db.execute(select(TrailRoute).where(TrailRoute.id == route_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")

    result = await db.execute(
        select(RouteSave).where(RouteSave.user_id == user_id, RouteSave.route_id == route_id)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already saved")

    db.add(RouteSave(user_id=user_id, route_id=route_id))
    await db.execute(
        update(TrailRoute)
        .where(TrailRoute.id == route_id)
        .values(saves_count=TrailRoute.saves_count + 1)
    )
    await db.flush()


async def unsave_route(db: AsyncSession, route_id: uuid.UUID, user_id: uuid.UUID) -> None:
    result = await db.execute(
        select(RouteSave).where(RouteSave.user_id == user_id, RouteSave.route_id == route_id)
    )
    save = result.scalar_one_or_none()
    if not save:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Save not found")

    await db.delete(save)
    await db.execute(
        update(TrailRoute)
        .where(TrailRoute.id == route_id)
        .values(saves_count=TrailRoute.saves_count - 1)
    )
    await db.flush()


async def get_saved_routes(
    db: AsyncSession,
    user_id: uuid.UUID,
    page: int,
    page_size: int,
) -> PaginatedResponse[RouteResponse]:
    saved_subq = (
        select(RouteSave.route_id).where(RouteSave.user_id == user_id).scalar_subquery()
    )

    total_result = await db.execute(
        select(func.count()).select_from(TrailRoute).where(TrailRoute.id.in_(saved_subq))
    )
    total = total_result.scalar_one()

    result = await db.execute(
        select(TrailRoute)
        .where(TrailRoute.id.in_(saved_subq))
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
