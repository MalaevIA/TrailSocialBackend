import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import (
    SubscriptionPlan,
    CreatorSubscription,
    SubscriptionStatus,
)
from app.models.user import User
from app.schemas.subscription import (
    SubscriptionPlanCreate,
    SubscriptionPlanUpdate,
    SubscriptionPlanResponse,
    CreatorSubscriptionResponse,
)

SUBSCRIPTION_DURATION_DAYS = 30


async def _get_plan_with_creator(
    db: AsyncSession, plan: SubscriptionPlan
) -> SubscriptionPlanResponse:
    result = await db.execute(select(User).where(User.id == plan.creator_id))
    creator = result.scalar_one_or_none()
    data = SubscriptionPlanResponse.model_validate(plan)
    data.creator = creator
    return data


# ── Plans ─────────────────────────────────────────────────────────────────────

async def create_or_update_plan(
    db: AsyncSession,
    creator_id: uuid.UUID,
    data: SubscriptionPlanCreate,
) -> SubscriptionPlanResponse:
    result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.creator_id == creator_id)
    )
    plan = result.scalar_one_or_none()

    if plan:
        await db.execute(
            update(SubscriptionPlan)
            .where(SubscriptionPlan.creator_id == creator_id)
            .values(
                price=data.price,
                description=data.description,
                is_active=True,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await db.flush()
        result = await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.creator_id == creator_id)
        )
        plan = result.scalar_one()
    else:
        plan = SubscriptionPlan(
            creator_id=creator_id,
            price=data.price,
            currency="RUB",
            description=data.description,
        )
        db.add(plan)
        await db.flush()

    return await _get_plan_with_creator(db, plan)


async def update_plan(
    db: AsyncSession,
    creator_id: uuid.UUID,
    data: SubscriptionPlanUpdate,
) -> SubscriptionPlanResponse:
    result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.creator_id == creator_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")

    updates = data.model_dump(exclude_none=True)
    updates["updated_at"] = datetime.now(timezone.utc)
    await db.execute(
        update(SubscriptionPlan)
        .where(SubscriptionPlan.creator_id == creator_id)
        .values(**updates)
    )
    await db.flush()

    result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.creator_id == creator_id)
    )
    plan = result.scalar_one()
    return await _get_plan_with_creator(db, plan)


async def get_plan_by_creator(
    db: AsyncSession, creator_id: uuid.UUID
) -> SubscriptionPlanResponse:
    result = await db.execute(
        select(SubscriptionPlan).where(
            SubscriptionPlan.creator_id == creator_id,
            SubscriptionPlan.is_active == True,  # noqa: E712
        )
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")
    return await _get_plan_with_creator(db, plan)


# ── Subscriptions ─────────────────────────────────────────────────────────────

async def activate_subscription(
    db: AsyncSession,
    subscriber_id: uuid.UUID,
    creator_id: uuid.UUID,
) -> CreatorSubscription:
    """Активировать или продлить подписку на 30 дней. Вызывается после успешной оплаты."""
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(CreatorSubscription).where(
            CreatorSubscription.subscriber_id == subscriber_id,
            CreatorSubscription.creator_id == creator_id,
            CreatorSubscription.status == SubscriptionStatus.active,
        )
    )
    sub = result.scalar_one_or_none()
    is_new = sub is None

    if sub:
        base = max(sub.expires_at, now)
        new_expires = base + timedelta(days=SUBSCRIPTION_DURATION_DAYS)
        await db.execute(
            update(CreatorSubscription)
            .where(CreatorSubscription.id == sub.id)
            .values(expires_at=new_expires)
        )
        await db.flush()
        sub.expires_at = new_expires
    else:
        sub = CreatorSubscription(
            subscriber_id=subscriber_id,
            creator_id=creator_id,
            status=SubscriptionStatus.active,
            expires_at=now + timedelta(days=SUBSCRIPTION_DURATION_DAYS),
        )
        db.add(sub)
        await db.flush()

    # Уведомить автора о новом платном подписчике (только при первой подписке, не при продлении)
    if is_new:
        from app.models.notification import NotificationType
        from app.services.notification_service import create_notification
        await create_notification(
            db,
            recipient_id=creator_id,
            actor_id=subscriber_id,
            type=NotificationType.new_paid_subscriber,
        )

    return sub


async def get_my_subscriptions(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[CreatorSubscriptionResponse]:
    """Мои активные подписки на авторов."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(CreatorSubscription).where(
            CreatorSubscription.subscriber_id == user_id,
            CreatorSubscription.status == SubscriptionStatus.active,
            CreatorSubscription.expires_at > now,
        )
    )
    subs = result.scalars().all()

    if not subs:
        return []

    creator_ids = [s.creator_id for s in subs]
    result = await db.execute(select(User).where(User.id.in_(creator_ids)))
    creators = {u.id: u for u in result.scalars().all()}

    items = []
    for sub in subs:
        data = CreatorSubscriptionResponse.model_validate(sub)
        data.creator = creators.get(sub.creator_id)
        items.append(data)
    return items


async def get_my_subscribers(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[CreatorSubscriptionResponse]:
    """Активные подписчики текущего пользователя."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(CreatorSubscription).where(
            CreatorSubscription.creator_id == user_id,
            CreatorSubscription.status == SubscriptionStatus.active,
            CreatorSubscription.expires_at > now,
        )
    )
    subs = result.scalars().all()

    if not subs:
        return []

    subscriber_ids = [s.subscriber_id for s in subs]
    result = await db.execute(select(User).where(User.id.in_(subscriber_ids)))
    subscribers = {u.id: u for u in result.scalars().all()}

    items = []
    for sub in subs:
        data = CreatorSubscriptionResponse.model_validate(sub)
        data.subscriber = subscribers.get(sub.subscriber_id)
        items.append(data)
    return items


async def check_subscription(
    db: AsyncSession,
    subscriber_id: uuid.UUID,
    creator_id: uuid.UUID,
) -> bool:
    """Проверить, есть ли активная подписка."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(CreatorSubscription.id).where(
            CreatorSubscription.subscriber_id == subscriber_id,
            CreatorSubscription.creator_id == creator_id,
            CreatorSubscription.status == SubscriptionStatus.active,
            CreatorSubscription.expires_at > now,
        )
    )
    return result.scalar_one_or_none() is not None


async def cancel_subscription(
    db: AsyncSession,
    subscriber_id: uuid.UUID,
    creator_id: uuid.UUID,
) -> None:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(CreatorSubscription).where(
            CreatorSubscription.subscriber_id == subscriber_id,
            CreatorSubscription.creator_id == creator_id,
            CreatorSubscription.status == SubscriptionStatus.active,
            CreatorSubscription.expires_at > now,
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active subscription not found")

    await db.execute(
        update(CreatorSubscription)
        .where(CreatorSubscription.id == sub.id)
        .values(status=SubscriptionStatus.cancelled)
    )
    await db.flush()
