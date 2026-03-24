import uuid

from fastapi import APIRouter

from app.dependencies import DbSession, CurrentUser
from app.schemas.subscription import (
    SubscriptionPlanCreate,
    SubscriptionPlanUpdate,
    SubscriptionPlanResponse,
    CreatorSubscriptionResponse,
)
from app.services import subscription_service

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


# ── Plans ─────────────────────────────────────────────────────────────────────

@router.put("/plans/my", response_model=SubscriptionPlanResponse)
async def upsert_my_plan(
    data: SubscriptionPlanCreate,
    current_user: CurrentUser,
    db: DbSession,
):
    """Создать или обновить свой тарифный план подписки."""
    return await subscription_service.create_or_update_plan(db, current_user.id, data)


@router.patch("/plans/my", response_model=SubscriptionPlanResponse)
async def patch_my_plan(
    data: SubscriptionPlanUpdate,
    current_user: CurrentUser,
    db: DbSession,
):
    """Частично обновить тарифный план (цену, описание, активность)."""
    return await subscription_service.update_plan(db, current_user.id, data)


@router.get("/plans/{creator_id}", response_model=SubscriptionPlanResponse)
async def get_creator_plan(creator_id: uuid.UUID, db: DbSession):
    """Посмотреть тариф конкретного автора."""
    return await subscription_service.get_plan_by_creator(db, creator_id)


# ── Subscriptions ─────────────────────────────────────────────────────────────

@router.get("/my", response_model=list[CreatorSubscriptionResponse])
async def my_subscriptions(current_user: CurrentUser, db: DbSession):
    """Мои активные подписки на авторов."""
    return await subscription_service.get_my_subscriptions(db, current_user.id)


@router.get("/subscribers", response_model=list[CreatorSubscriptionResponse])
async def my_subscribers(current_user: CurrentUser, db: DbSession):
    """Мои активные подписчики."""
    return await subscription_service.get_my_subscribers(db, current_user.id)


@router.delete("/cancel/{creator_id}", status_code=204)
async def cancel_subscription(
    creator_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
):
    """Отменить подписку на автора."""
    await subscription_service.cancel_subscription(db, current_user.id, creator_id)
