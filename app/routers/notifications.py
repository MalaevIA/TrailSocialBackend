import uuid

from fastapi import APIRouter

from app.dependencies import DbSession, CurrentUser
from app.schemas.common import PaginatedResponse
from app.schemas.notification import NotificationResponse, UnreadCountResponse
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=PaginatedResponse[NotificationResponse])
async def list_notifications(
    current_user: CurrentUser,
    db: DbSession,
    page: int = 1,
    page_size: int = 20,
    unread_only: bool = False,
):
    return await notification_service.list_notifications(
        db, current_user.id, page, page_size, unread_only
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
async def unread_count(current_user: CurrentUser, db: DbSession):
    return await notification_service.get_unread_count(db, current_user.id)


@router.post("/read-all", status_code=204)
async def read_all(current_user: CurrentUser, db: DbSession):
    await notification_service.mark_all_as_read(db, current_user.id)


@router.post("/{notification_id}/read", status_code=204)
async def read_one(notification_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await notification_service.mark_as_read(db, notification_id, current_user.id)
