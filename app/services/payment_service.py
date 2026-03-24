import asyncio
import logging
import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.subscription import (
    Payment,
    PaymentStatus,
    SubscriptionPlan,
)
from app.schemas.subscription import CheckoutRequest, CheckoutResponse
from app.services.subscription_service import activate_subscription

logger = logging.getLogger(__name__)


async def create_checkout(
    db: AsyncSession,
    payer_id: uuid.UUID,
    data: CheckoutRequest,
) -> CheckoutResponse:
    """
    Провести оплату подписки через токен YooKassa Android SDK.

    Возможные ответы:
    - status=success  — оплата прошла сразу, подписка активирована
    - status=pending  — требуется 3DS, клиент открывает confirmation_url,
                        после чего webhook активирует подписку автоматически
    """
    if payer_id == data.creator_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot subscribe to yourself",
        )

    # 1. Получить активный тарифный план автора
    result = await db.execute(
        select(SubscriptionPlan).where(
            SubscriptionPlan.creator_id == data.creator_id,
            SubscriptionPlan.is_active == True,  # noqa: E712
        )
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creator does not have an active subscription plan",
        )

    # 2. Создать запись платежа в БД
    payment = Payment(
        payer_id=payer_id,
        creator_id=data.creator_id,
        amount=plan.price,
        currency=plan.currency,
        status=PaymentStatus.pending,
    )
    db.add(payment)
    await db.flush()

    # 3. Вызвать YooKassa API с payment_token
    yoo_payment_id, yoo_status, confirmation_url = await _charge_with_token(
        payment=payment,
        payment_token=data.payment_token,
        return_url=data.return_url,
        creator_yookassa_account_id=plan.yookassa_account_id,
    )

    # 4. Обработать результат
    if yoo_status == "succeeded":
        await db.execute(
            update(Payment)
            .where(Payment.id == payment.id)
            .values(status=PaymentStatus.completed, yookassa_payment_id=yoo_payment_id)
        )
        sub = await activate_subscription(db, payer_id, data.creator_id)
        await db.execute(
            update(Payment).where(Payment.id == payment.id).values(subscription_id=sub.id)
        )
        logger.info(
            "Payment %s succeeded → subscription activated for user %s → creator %s",
            payment.id, payer_id, data.creator_id,
        )
        return CheckoutResponse(status="success", payment_id=yoo_payment_id)

    elif yoo_status == "pending":
        # Сохраняем yookassa_payment_id — нужен для идемпотентности webhook
        await db.execute(
            update(Payment)
            .where(Payment.id == payment.id)
            .values(yookassa_payment_id=yoo_payment_id, confirmation_url=confirmation_url)
        )
        logger.info("Payment %s pending 3DS, confirmation_url sent to client", payment.id)
        return CheckoutResponse(status="pending", confirmation_url=confirmation_url, payment_id=yoo_payment_id)

    else:
        await db.execute(
            update(Payment)
            .where(Payment.id == payment.id)
            .values(status=PaymentStatus.failed, yookassa_payment_id=yoo_payment_id)
        )
        logger.warning("Payment %s not succeeded, yookassa status=%s", payment.id, yoo_status)
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Payment not completed, status: {yoo_status}",
        )


def _calc_creator_amount(total: Decimal, currency: str) -> dict:
    """Рассчитать долю автора: (100 - PLATFORM_FEE_PERCENT)% от суммы, округление до 2 знаков."""
    creator_share = Decimal(100 - settings.PLATFORM_FEE_PERCENT) / Decimal(100)
    creator_amount = (total * creator_share).quantize(Decimal("0.01"))
    return {"value": str(creator_amount), "currency": currency}


def _do_yookassa_charge(payload: dict, idempotency_key: str):
    """Синхронный вызов YooKassa SDK — запускается в thread pool."""
    from yookassa import Configuration, Payment as YooPayment

    Configuration.account_id = settings.YOOKASSA_SHOP_ID
    Configuration.secret_key = settings.YOOKASSA_SECRET_KEY

    return YooPayment.create(payload, idempotency_key=idempotency_key)


async def _charge_with_token(
    payment: Payment,
    payment_token: str,
    return_url: str,
    creator_yookassa_account_id: str | None,
) -> tuple[str, str, str | None]:
    """
    Создаёт платёж через YooKassa с payment_token от Android SDK.
    Возвращает (yookassa_payment_id, status, confirmation_url | None).

    status='succeeded' — оплата прошла без 3DS.
    status='pending'   — нужна 3DS, confirmation_url передаётся клиенту.
    """
    if not settings.YOOKASSA_SHOP_ID or not settings.YOOKASSA_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment provider is not configured",
        )

    try:
        from yookassa import Configuration  # noqa: F401 — проверка наличия SDK
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment provider SDK not installed",
        )

    payload: dict = {
        "amount": {
            "value": str(payment.amount),
            "currency": payment.currency,
        },
        "payment_token": payment_token,
        "capture": True,
        "description": f"Подписка на автора. Платёж {payment.id}",
        # confirmation нужен для 3DS-редиректа
        "confirmation": {
            "type": "redirect",
            "return_url": return_url,
        },
        "metadata": {
            "payment_id": str(payment.id),
            "payer_id": str(payment.payer_id),
            "creator_id": str(payment.creator_id),
        },
    }

    # Сплит: автор получает (100 - PLATFORM_FEE_PERCENT)% автоматически
    if creator_yookassa_account_id:
        payload["transfers"] = [
            {
                "account_id": creator_yookassa_account_id,
                "amount": _calc_creator_amount(payment.amount, payment.currency),
            }
        ]

    try:
        # SDK синхронный — выносим в thread pool, чтобы не блокировать event loop
        yoo_payment = await asyncio.to_thread(
            _do_yookassa_charge, payload, str(payment.id)
        )
    except Exception as exc:
        logger.error("YooKassa API error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment provider unavailable",
        )

    confirmation_url: str | None = None
    if yoo_payment.status == "pending" and yoo_payment.confirmation:
        confirmation_url = getattr(yoo_payment.confirmation, "confirmation_url", None)

    return yoo_payment.id, yoo_payment.status, confirmation_url


def _do_yookassa_fetch(yoo_payment_id: str):
    """Синхронный запрос статуса платежа из YooKassa — запускается в thread pool."""
    from yookassa import Configuration, Payment as YooPayment

    Configuration.account_id = settings.YOOKASSA_SHOP_ID
    Configuration.secret_key = settings.YOOKASSA_SECRET_KEY

    return YooPayment.find_one(yoo_payment_id)


async def verify_payment(
    db: AsyncSession,
    payer_id: uuid.UUID,
    yookassa_payment_id: str,
) -> CheckoutResponse:
    """
    Проверить статус платежа в YooKassa и активировать подписку если succeeded.
    Вызывается клиентом после редиректа с 3DS-страницы.
    Идемпотентен — повторный вызов для уже активированного платежа вернёт success.
    """
    # Найти платёж в БД
    result = await db.execute(
        select(Payment).where(
            Payment.yookassa_payment_id == yookassa_payment_id,
            Payment.payer_id == payer_id,
        )
    )
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")

    # Уже обработан
    if payment.status == PaymentStatus.completed:
        return CheckoutResponse(status="success")
    if payment.status == PaymentStatus.failed:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Payment failed",
        )

    if not settings.YOOKASSA_SHOP_ID or not settings.YOOKASSA_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment provider is not configured",
        )

    # Запросить актуальный статус из YooKassa
    try:
        yoo_payment = await asyncio.to_thread(_do_yookassa_fetch, yookassa_payment_id)
    except Exception as exc:
        logger.error("YooKassa fetch error for %s: %s", yookassa_payment_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment provider unavailable",
        )

    if yoo_payment.status == "succeeded":
        await db.execute(
            update(Payment)
            .where(Payment.id == payment.id)
            .values(status=PaymentStatus.completed)
        )
        sub = await activate_subscription(db, payment.payer_id, payment.creator_id)
        await db.execute(
            update(Payment).where(Payment.id == payment.id).values(subscription_id=sub.id)
        )
        logger.info("verify_payment: payment %s succeeded → subscription activated", payment.id)
        return CheckoutResponse(status="success")

    elif yoo_payment.status == "pending":
        return CheckoutResponse(
            status="pending",
            confirmation_url=getattr(
                getattr(yoo_payment, "confirmation", None), "confirmation_url", None
            ),
        )

    else:
        await db.execute(
            update(Payment)
            .where(Payment.id == payment.id)
            .values(status=PaymentStatus.failed)
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Payment not completed, status: {yoo_payment.status}",
        )


async def handle_webhook(db: AsyncSession, event: dict) -> None:
    """Обработать webhook-уведомление от ЮКассы (дополнительная надёжность)."""
    event_type = event.get("event")
    payment_obj = event.get("object", {})

    if event_type not in ("payment.succeeded", "payment.canceled"):
        return

    yoo_payment_id = payment_obj.get("id")
    metadata = payment_obj.get("metadata", {})
    payment_id_str = metadata.get("payment_id")

    if not payment_id_str:
        logger.warning("YooKassa webhook: no payment_id in metadata, yoo_id=%s", yoo_payment_id)
        return

    try:
        payment_id = uuid.UUID(payment_id_str)
    except ValueError:
        logger.warning("YooKassa webhook: invalid payment_id=%s", payment_id_str)
        return

    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()
    if not payment or payment.status != PaymentStatus.pending:
        return

    if event_type == "payment.succeeded":
        await db.execute(
            update(Payment)
            .where(Payment.id == payment_id)
            .values(status=PaymentStatus.completed, yookassa_payment_id=yoo_payment_id)
        )
        sub = await activate_subscription(db, payment.payer_id, payment.creator_id)
        await db.execute(
            update(Payment).where(Payment.id == payment_id).values(subscription_id=sub.id)
        )
        logger.info("Webhook: payment %s succeeded → subscription activated", payment_id)
    else:
        await db.execute(
            update(Payment)
            .where(Payment.id == payment_id)
            .values(status=PaymentStatus.cancelled)
        )
        logger.info("Webhook: payment %s cancelled", payment_id)

    await db.flush()
