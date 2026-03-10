import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comment import Comment
from app.models.notification import Notification, NotificationType
from app.models.route import TrailRoute
from app.models.user import User, Follow
from app.schemas.common import PaginatedResponse
from app.schemas.notification import NotificationResponse, UnreadCountResponse


async def _enrich_notifications(
    db: AsyncSession,
    notifications: list[Notification],
) -> list[NotificationResponse]:
    """Bulk-enrich notifications: actors, route titles, comment texts."""
    if not notifications:
        return []

    actor_ids = list({n.actor_id for n in notifications})
    result = await db.execute(select(User).where(User.id.in_(actor_ids)))
    actors = {u.id: u for u in result.scalars().all()}

    route_ids = [n.route_id for n in notifications if n.route_id is not None]
    routes: dict[uuid.UUID, TrailRoute] = {}
    if route_ids:
        result = await db.execute(
            select(TrailRoute.id, TrailRoute.title).where(TrailRoute.id.in_(route_ids))
        )
        routes = {row.id: row for row in result.all()}

    comment_ids = [n.comment_id for n in notifications if n.comment_id is not None]
    comments: dict[uuid.UUID, Comment] = {}
    if comment_ids:
        result = await db.execute(
            select(Comment.id, Comment.text).where(Comment.id.in_(comment_ids))
        )
        comments = {row.id: row for row in result.all()}

    enriched = []
    for n in notifications:
        route = routes.get(n.route_id) if n.route_id else None
        comment = comments.get(n.comment_id) if n.comment_id else None
        enriched.append(
            NotificationResponse(
                id=n.id,
                type=n.type,
                is_read=n.is_read,
                created_at=n.created_at,
                actor=actors[n.actor_id],
                route_id=n.route_id,
                route_title=route.title if route else None,
                comment_id=n.comment_id,
                comment_text=comment.text if comment else None,
            )
        )
    return enriched


async def create_notification(
    db: AsyncSession,
    recipient_id: uuid.UUID,
    actor_id: uuid.UUID,
    type: NotificationType,
    route_id: Optional[uuid.UUID] = None,
    comment_id: Optional[uuid.UUID] = None,
) -> None:
    """Create a notification. Silently skips self-notifications. Pushes via WS."""
    if recipient_id == actor_id:
        return

    notification = Notification(
        recipient_id=recipient_id,
        actor_id=actor_id,
        type=type,
        route_id=route_id,
        comment_id=comment_id,
    )
    db.add(notification)
    await db.flush()  # чтобы получить notification.id и created_at

    # Real-time push если пользователь онлайн
    from app.core.ws_manager import ws_manager
    if ws_manager.is_online(recipient_id):
        # Обогащаем для WS-отправки
        enriched = await _enrich_notifications(db, [notification])
        if enriched:
            await ws_manager.send_to_user(
                recipient_id, enriched[0].model_dump(mode="json")
            )


async def notify_followers_new_route(
    db: AsyncSession,
    author_id: uuid.UUID,
    route_id: uuid.UUID,
) -> None:
    """Notify all followers of the author about a new published route."""
    result = await db.execute(
        select(Follow.follower_id).where(Follow.following_id == author_id)
    )
    follower_ids = result.scalars().all()

    if not follower_ids:
        return

    from app.core.ws_manager import ws_manager

    notifications = []
    for fid in follower_ids:
        n = Notification(
            recipient_id=fid,
            actor_id=author_id,
            type=NotificationType.new_route,
            route_id=route_id,
        )
        db.add(n)
        notifications.append(n)

    await db.flush()

    # Real-time push to online followers
    online = [n for n in notifications if ws_manager.is_online(n.recipient_id)]
    if online:
        enriched = await _enrich_notifications(db, online)
        for notif, enriched_notif in zip(online, enriched):
            await ws_manager.send_to_user(
                notif.recipient_id, enriched_notif.model_dump(mode="json")
            )


async def list_notifications(
    db: AsyncSession,
    user_id: uuid.UUID,
    page: int,
    page_size: int,
    unread_only: bool,
) -> PaginatedResponse[NotificationResponse]:
    base_filter = Notification.recipient_id == user_id
    if unread_only:
        base_filter = base_filter & (Notification.is_read == False)  # noqa: E712

    total_result = await db.execute(
        select(func.count()).select_from(Notification).where(base_filter)
    )
    total = total_result.scalar_one()

    result = await db.execute(
        select(Notification)
        .where(base_filter)
        .order_by(Notification.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    notifications = result.scalars().all()

    items = await _enrich_notifications(db, list(notifications))
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if total else 0,
    )


async def get_unread_count(db: AsyncSession, user_id: uuid.UUID) -> UnreadCountResponse:
    result = await db.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.recipient_id == user_id, Notification.is_read == False)  # noqa: E712
    )
    return UnreadCountResponse(count=result.scalar_one())


async def mark_as_read(
    db: AsyncSession, notification_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    result = await db.execute(
        select(Notification).where(Notification.id == notification_id)
    )
    notification = result.scalar_one_or_none()
    if not notification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    if notification.recipient_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your notification")

    await db.execute(
        update(Notification)
        .where(Notification.id == notification_id)
        .values(is_read=True)
    )
    await db.flush()


async def mark_all_as_read(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(Notification)
        .where(Notification.recipient_id == user_id, Notification.is_read == False)  # noqa: E712
        .values(is_read=True)
    )
    await db.flush()
