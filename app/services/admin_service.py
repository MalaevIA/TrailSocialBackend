import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select, update, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.route import TrailRoute
from app.models.comment import Comment
from app.schemas.common import PaginatedResponse
from app.schemas.user import UserPublic


async def list_users(
    db: AsyncSession,
    page: int,
    page_size: int,
    q: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> PaginatedResponse[UserPublic]:
    filters = []
    if q:
        pattern = f"%{q}%"
        filters.append(User.username.ilike(pattern) | User.display_name.ilike(pattern))
    if is_active is not None:
        filters.append(User.is_active == is_active)

    count_query = select(func.count()).select_from(User)
    query = select(User)

    if filters:
        count_query = count_query.where(*filters)
        query = query.where(*filters)

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    result = await db.execute(
        query.order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    users = result.scalars().all()

    items = [UserPublic.model_validate(u) for u in users]
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if total else 0,
    )


async def ban_user(db: AsyncSession, user_id: uuid.UUID) -> UserPublic:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.is_admin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot ban an admin")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is already banned")

    await db.execute(
        update(User).where(User.id == user_id).values(
            is_active=False, updated_at=datetime.now(timezone.utc)
        )
    )
    await db.flush()

    result = await db.execute(select(User).where(User.id == user_id))
    return UserPublic.model_validate(result.scalar_one())


async def unban_user(db: AsyncSession, user_id: uuid.UUID) -> UserPublic:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is not banned")

    await db.execute(
        update(User).where(User.id == user_id).values(
            is_active=True, updated_at=datetime.now(timezone.utc)
        )
    )
    await db.flush()

    result = await db.execute(select(User).where(User.id == user_id))
    return UserPublic.model_validate(result.scalar_one())


async def delete_route(db: AsyncSession, route_id: uuid.UUID) -> None:
    result = await db.execute(select(TrailRoute).where(TrailRoute.id == route_id))
    route = result.scalar_one_or_none()
    if not route:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")

    author_id = route.author_id
    await db.delete(route)
    await db.execute(
        update(User).where(User.id == author_id).values(routes_count=User.routes_count - 1)
    )
    await db.flush()


async def delete_comment(db: AsyncSession, comment_id: uuid.UUID) -> None:
    result = await db.execute(select(Comment).where(Comment.id == comment_id))
    comment = result.scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")

    route_id = comment.route_id
    await db.delete(comment)
    await db.execute(
        update(TrailRoute)
        .where(TrailRoute.id == route_id)
        .values(comments_count=TrailRoute.comments_count - 1)
    )
    await db.flush()
