import uuid

from fastapi import APIRouter

from app.dependencies import DbSession, CurrentUser, OptionalUser
from app.schemas.comment import CommentCreate, CommentResponse
from app.schemas.common import PaginatedResponse
from app.services import comment_service

router = APIRouter(tags=["comments"])


@router.get("/routes/{route_id}/comments", response_model=PaginatedResponse[CommentResponse])
async def list_comments(
    route_id: uuid.UUID,
    db: DbSession,
    current_user: OptionalUser,
    page: int = 1,
    page_size: int = 20,
):
    opt_id = current_user.id if current_user else None
    return await comment_service.list_comments(db, route_id, page, page_size, opt_id)


@router.post(
    "/routes/{route_id}/comments",
    response_model=CommentResponse,
    status_code=201,
)
async def create_comment(
    route_id: uuid.UUID, data: CommentCreate, current_user: CurrentUser, db: DbSession
):
    return await comment_service.create_comment(db, route_id, current_user.id, data)


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(comment_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await comment_service.delete_comment(db, comment_id, current_user.id)


@router.post("/comments/{comment_id}/like", status_code=204)
async def like_comment(comment_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await comment_service.like_comment(db, comment_id, current_user.id)


@router.delete("/comments/{comment_id}/like", status_code=204)
async def unlike_comment(comment_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await comment_service.unlike_comment(db, comment_id, current_user.id)
