import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.notification import NotificationType
from app.schemas.user import UserPublic


class NotificationResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    type: NotificationType
    is_read: bool
    created_at: datetime
    actor: UserPublic
    route_id: Optional[uuid.UUID] = None
    route_title: Optional[str] = None
    comment_id: Optional[uuid.UUID] = None
    comment_text: Optional[str] = None


class UnreadCountResponse(BaseModel):
    count: int
