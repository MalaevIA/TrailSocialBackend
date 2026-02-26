from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import decode_token
from app.core.ws_manager import ws_manager
from app.models.user import User

router = APIRouter()


async def _authenticate_ws(token: str | None):
    """Проверяет JWT из query-параметра, возвращает user_id или None."""
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
        return user.id


@router.websocket("/ws/notifications")
async def ws_notifications(ws: WebSocket, token: str = Query(default="")):
    user_id = await _authenticate_ws(token)
    if not user_id:
        await ws.close(code=4001, reason="Unauthorized")
        return

    await ws_manager.connect(user_id, ws)
    try:
        while True:
            # Держим соединение открытым, клиент может слать ping / keep-alive
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(user_id, ws)
