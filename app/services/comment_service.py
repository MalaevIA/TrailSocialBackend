import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comment import Comment, CommentLike
from app.models.route import TrailRoute
from app.models.user import User
from app.schemas.comment import CommentCreate, CommentResponse
from app.schemas.common import PaginatedResponse


async def _enrich_comments(
    db: AsyncSession,
    comments: list[Comment],
    user_id: Optional[uuid.UUID],
) -> list[CommentResponse]:
    if not comments:
        return []

    comment_ids = [c.id for c in comments]
    author_ids = list({c.author_id for c in comments})

    result = await db.execute(select(User).where(User.id.in_(author_ids)))
    authors = {u.id: u for u in result.scalars().all()}

    liked_set: set[uuid.UUID] = set()
    if user_id:
        result = await db.execute(
            select(CommentLike.comment_id).where(
                CommentLike.user_id == user_id,
                CommentLike.comment_id.in_(comment_ids),
            )
        )
        liked_set = {row for row in result.scalars().all()}

    enriched = []
    for comment in comments:
        data = CommentResponse.model_validate(comment)
        data.author = authors[comment.author_id]
        data.is_liked = comment.id in liked_set
        enriched.append(data)

    return enriched


async def list_comments(
    db: AsyncSession,
    route_id: uuid.UUID,
    page: int,
    page_size: int,
    user_id: Optional[uuid.UUID],
) -> PaginatedResponse[CommentResponse]:
    # Verify route exists
    result = await db.execute(select(TrailRoute).where(TrailRoute.id == route_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")

    count_result = await db.execute(
        select(func.count()).select_from(Comment).where(Comment.route_id == route_id)
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(Comment)
        .where(Comment.route_id == route_id)
        .order_by(Comment.created_at.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    comments = result.scalars().all()

    items = await _enrich_comments(db, list(comments), user_id)
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if total else 0,
    )


async def create_comment(
    db: AsyncSession,
    route_id: uuid.UUID,
    user_id: uuid.UUID,
    data: CommentCreate,
) -> CommentResponse:
    from app.models.notification import NotificationType
    from app.services.notification_service import create_notification

    result = await db.execute(select(TrailRoute).where(TrailRoute.id == route_id))
    route = result.scalar_one_or_none()
    if not route:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")

    comment = Comment(route_id=route_id, author_id=user_id, text=data.text)
    db.add(comment)

    await db.execute(
        update(TrailRoute)
        .where(TrailRoute.id == route_id)
        .values(comments_count=TrailRoute.comments_count + 1)
    )
    await db.flush()

    await create_notification(
        db,
        recipient_id=route.author_id,
        actor_id=user_id,
        type=NotificationType.new_comment,
        route_id=route_id,
        comment_id=comment.id,
    )

    result = await db.execute(select(Comment).where(Comment.id == comment.id))
    comment = result.scalar_one()
    items = await _enrich_comments(db, [comment], user_id)
    return items[0]


async def delete_comment(
    db: AsyncSession,
    comment_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    result = await db.execute(select(Comment).where(Comment.id == comment_id))
    comment = result.scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    if comment.author_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the author")

    route_id = comment.route_id
    await db.delete(comment)
    await db.execute(
        update(TrailRoute)
        .where(TrailRoute.id == route_id)
        .values(comments_count=TrailRoute.comments_count - 1)
    )
    await db.flush()


async def like_comment(
    db: AsyncSession,
    comment_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    result = await db.execute(select(Comment).where(Comment.id == comment_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")

    result = await db.execute(
        select(CommentLike).where(
            CommentLike.user_id == user_id, CommentLike.comment_id == comment_id
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already liked")

    db.add(CommentLike(user_id=user_id, comment_id=comment_id))
    await db.execute(
        update(Comment)
        .where(Comment.id == comment_id)
        .values(likes_count=Comment.likes_count + 1)
    )
    await db.flush()


async def unlike_comment(
    db: AsyncSession,
    comment_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    result = await db.execute(
        select(CommentLike).where(
            CommentLike.user_id == user_id, CommentLike.comment_id == comment_id
        )
    )
    like = result.scalar_one_or_none()
    if not like:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Like not found")

    await db.delete(like)
    await db.execute(
        update(Comment)
        .where(Comment.id == comment_id)
        .values(likes_count=Comment.likes_count - 1)
    )
    await db.flush()
