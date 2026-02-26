import uuid
from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    """Менеджер WebSocket-соединений, привязанных к user_id."""

    def __init__(self):
        self._connections: dict[uuid.UUID, list[WebSocket]] = defaultdict(list)

    async def connect(self, user_id: uuid.UUID, ws: WebSocket):
        await ws.accept()
        self._connections[user_id].append(ws)

    def disconnect(self, user_id: uuid.UUID, ws: WebSocket):
        conns = self._connections.get(user_id, [])
        if ws in conns:
            conns.remove(ws)
        if not conns:
            self._connections.pop(user_id, None)

    async def send_to_user(self, user_id: uuid.UUID, data: dict):
        """Отправить JSON-сообщение всем подключениям пользователя."""
        conns = self._connections.get(user_id, [])
        dead = []
        for ws in conns:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(user_id, ws)

    def is_online(self, user_id: uuid.UUID) -> bool:
        return bool(self._connections.get(user_id))


ws_manager = ConnectionManager()
