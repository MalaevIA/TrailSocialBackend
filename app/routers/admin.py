import uuid
from typing import Optional

from fastapi import APIRouter, Query

from app.dependencies import AdminUser, DbSession
from app.schemas.common import PaginatedResponse
from app.schemas.user import UserPublic
from app.services import admin_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=PaginatedResponse[UserPublic])
async def list_users(
    db: DbSession,
    admin: AdminUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: Optional[str] = None,
    is_active: Optional[bool] = None,
):
    return await admin_service.list_users(db, page, page_size, q, is_active)


@router.post("/users/{user_id}/ban", response_model=UserPublic)
async def ban_user(
    user_id: uuid.UUID,
    db: DbSession,
    admin: AdminUser,
):
    return await admin_service.ban_user(db, user_id)


@router.post("/users/{user_id}/unban", response_model=UserPublic)
async def unban_user(
    user_id: uuid.UUID,
    db: DbSession,
    admin: AdminUser,
):
    return await admin_service.unban_user(db, user_id)


@router.delete("/routes/{route_id}", status_code=204)
async def delete_route(
    route_id: uuid.UUID,
    db: DbSession,
    admin: AdminUser,
):
    await admin_service.delete_route(db, route_id)


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: uuid.UUID,
    db: DbSession,
    admin: AdminUser,
):
    await admin_service.delete_comment(db, comment_id)
