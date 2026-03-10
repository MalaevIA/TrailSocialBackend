import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


class UserPublic(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    username: str
    display_name: str
    avatar_url: Optional[str]
    bio: Optional[str]
    followers_count: int
    following_count: int
    routes_count: int
    created_at: datetime
    is_admin: bool = False
    is_active: bool = True


class UserProfile(UserPublic):
    is_following: bool = False


class UpdateProfileRequest(BaseModel):
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def new_password_min_length(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
        return v
