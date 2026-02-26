import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.schemas.user import UserPublic


class CommentCreate(BaseModel):
    text: str


class CommentResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    route_id: uuid.UUID
    text: str
    likes_count: int
    created_at: datetime
    updated_at: datetime
    author: Optional[UserPublic] = None
    is_liked: bool = False
