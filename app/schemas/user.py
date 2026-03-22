import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


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
    display_name: Optional[str] = Field(None, min_length=1, max_length=100)
    bio: Optional[str] = Field(None, max_length=1000)
    avatar_url: Optional[str] = None

    @field_validator("avatar_url")
    @classmethod
    def avatar_url_must_be_http(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("avatar_url must be an http or https URL")
        return v


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def new_password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class ChangeEmailRequest(BaseModel):
    new_email: str
    password: str

    @field_validator("new_email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        import re
        if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', v):
            raise ValueError("Invalid email address")
        return v.lower().strip()
