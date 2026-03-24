import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.models.subscription import SubscriptionStatus, PaymentStatus
from app.schemas.user import UserPublic


# ── Subscription Plan ─────────────────────────────────────────────────────────

class SubscriptionPlanCreate(BaseModel):
    price: Decimal = Field(..., gt=0, description="Цена подписки в рублях, например 299.00")
    description: Optional[str] = Field(None, max_length=500)
    yookassa_account_id: Optional[str] = Field(
        None, description="ID аккаунта в ЮКасса Marketplace для автоматических выплат"
    )


class SubscriptionPlanUpdate(BaseModel):
    price: Optional[Decimal] = Field(None, gt=0)
    description: Optional[str] = Field(None, max_length=500)
    yookassa_account_id: Optional[str] = None
    is_active: Optional[bool] = None


class SubscriptionPlanResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    creator_id: uuid.UUID
    price: Decimal
    currency: str
    description: Optional[str]
    yookassa_account_id: Optional[str]
    is_active: bool
    created_at: datetime
    creator: Optional[UserPublic] = None


# ── Creator Subscription ──────────────────────────────────────────────────────

class CreatorSubscriptionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    subscriber_id: uuid.UUID
    creator_id: uuid.UUID
    status: SubscriptionStatus
    expires_at: datetime
    created_at: datetime
    creator: Optional[UserPublic] = None      # заполняется в GET /subscriptions/my
    subscriber: Optional[UserPublic] = None   # заполняется в GET /subscriptions/subscribers


# ── Payment ───────────────────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    creator_id: uuid.UUID
    payment_token: str = Field(..., description="Токен от YooKassa Android SDK")
    return_url: str = Field(..., description="Deep link для редиректа после 3DS, напр. trailsocial://payment/result")


class CheckoutResponse(BaseModel):
    # "success" — подписка активирована сразу
    # "pending" — требуется 3DS, открыть confirmation_url в браузере
    status: str
    confirmation_url: Optional[str] = None
    payment_id: Optional[str] = None  # YooKassa payment ID для вызова /verify/{payment_id}
