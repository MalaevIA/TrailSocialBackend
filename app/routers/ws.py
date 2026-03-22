import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import decode_token
from app.core.ws_manager import ws_manager
from app.models.user import User

router = APIRouter()

_AUTH_TIMEOUT_SECONDS = settings.WS_AUTH_TIMEOUT_SECONDS


async def _authenticate_ws(token: str | None, ws: WebSocket):
    """Проверяет JWT, возвращает user_id или None.
    Токен передаётся в первом JSON-сообщении {"token": "..."} после connect,
    а не в query string (иначе попадает в access-логи сервера).
    """
    if not token:
        return None
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        return None

    user_id = payload.get("sub")
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user or not user.is_active:
            return None
        if payload.get("tv", 0) != user.token_version:
            return None
        return user.id


@router.websocket("/ws/notifications")
async def ws_notifications(ws: WebSocket):
    await ws.accept()

    # Клиент должен прислать {"token": "<access_token>"} в течение 10 секунд
    try:
        auth_data = await asyncio.wait_for(ws.receive_json(), timeout=_AUTH_TIMEOUT_SECONDS)
        token = auth_data.get("token", "") if isinstance(auth_data, dict) else ""
    except (asyncio.TimeoutError, Exception):
        await ws.close(code=4001, reason="Unauthorized")
        return

    user_id = await _authenticate_ws(token, ws)
    if not user_id:
        await ws.close(code=4001, reason="Unauthorized")
        return

    ws_manager.connect(user_id, ws)
    try:
        while True:
            # Держим соединение открытым, клиент может слать ping / keep-alive
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(user_id, ws)
