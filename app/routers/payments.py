import logging

from fastapi import APIRouter, Request, HTTPException, status

from app.dependencies import DbSession, CurrentUser
from app.schemas.subscription import CheckoutRequest, CheckoutResponse
from app.services import payment_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/checkout", response_model=CheckoutResponse, status_code=200)
async def checkout(
    data: CheckoutRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    Оплатить подписку на автора через токен YooKassa Android SDK.
    Токен формируется на стороне приложения через YooKassa SDK и передаётся сюда.
    Платёж проводится синхронно — при успехе сразу активируется подписка.

    Ошибки:
    - 404 — у автора нет активного тарифного плана
    - 402 — платёж не прошёл (отклонён банком и т.п.)
    - 503 — YooKassa недоступна
    """
    return await payment_service.create_checkout(db, current_user.id, data)


@router.post("/verify/{yookassa_payment_id}", response_model=CheckoutResponse, status_code=200)
async def verify_payment(
    yookassa_payment_id: str,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    Проверить статус платежа и активировать подписку если 3DS пройден.
    Вызывать после того как пользователь вернулся с 3DS-страницы.
    Идемпотентен — безопасно вызывать несколько раз.

    Ответы:
    - {"status": "success"} — подписка активирована
    - {"status": "pending"} — ещё не оплачен
    - 402 — платёж отклонён
    """
    return await payment_service.verify_payment(db, current_user.id, yookassa_payment_id)


@router.post("/webhook", status_code=200)
async def yookassa_webhook(request: Request, db: DbSession):
    """
    Webhook-эндпоинт для ЮКассы.
    ЮКасса отправляет POST с IP из диапазона 185.71.76.0/27 и 185.71.77.0/27.
    URL прописать в личном кабинете: Интеграция → HTTP-уведомления.
    """
    # Валидация IP ЮКассы (защита от посторонних запросов)
    client_ip = request.client.host if request.client else ""
    if not _is_yookassa_ip(client_ip):
        logger.warning("Webhook from unknown IP: %s", client_ip)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    try:
        event = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    await payment_service.handle_webhook(db, event)
    return {"status": "ok"}


def _is_yookassa_ip(ip: str) -> bool:
    """Проверить что запрос пришёл с IP-адреса ЮКассы."""
    import ipaddress
    try:
        addr = ipaddress.ip_address(ip)
        # Официальные диапазоны ЮКассы + ngrok для локальной разработки
        allowed = [
            ipaddress.ip_network("185.71.76.0/27"),
            ipaddress.ip_network("185.71.77.0/27"),
            ipaddress.ip_network("77.75.153.0/25"),
            ipaddress.ip_network("77.75.156.11/32"),
            ipaddress.ip_network("77.75.156.35/32"),
            ipaddress.ip_network("77.75.154.128/25"),
        ]
        return any(addr in net for net in allowed)
    except ValueError:
        return False
