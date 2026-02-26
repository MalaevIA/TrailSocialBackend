import uuid
from typing import Optional, List

from fastapi import APIRouter, Query

from app.dependencies import DbSession, CurrentUser, OptionalUser
from app.schemas.common import PaginatedResponse
from app.schemas.route import RouteResponse
from app.models.route import Difficulty
from app.schemas.route import SortOrder
from app.schemas.user import UserPublic, UserProfile, UpdateProfileRequest, ChangePasswordRequest
from app.services import user_service, route_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserPublic)
async def get_me(current_user: CurrentUser):
    return current_user


@router.put("/me", response_model=UserPublic)
async def update_me(data: UpdateProfileRequest, current_user: CurrentUser, db: DbSession):
    updated = await user_service.update_profile(db, current_user, data)
    return updated


@router.put("/me/password", status_code=204)
async def change_password(data: ChangePasswordRequest, current_user: CurrentUser, db: DbSession):
    await user_service.change_password(db, current_user, data.current_password, data.new_password)


@router.get("/me/saved-routes", response_model=PaginatedResponse[RouteResponse])
async def get_saved_routes(
    current_user: CurrentUser,
    db: DbSession,
    page: int = 1,
    page_size: int = 20,
):
    return await route_service.get_saved_routes(db, current_user.id, page, page_size)


@router.get("/{user_id}", response_model=UserProfile)
async def get_user(
    user_id: uuid.UUID,
    db: DbSession,
    current_user: OptionalUser,
):
    opt_id = current_user.id if current_user else None
    return await user_service.get_user_profile(db, user_id, opt_id)


@router.get("/{user_id}/routes", response_model=PaginatedResponse[RouteResponse])
async def get_user_routes(
    user_id: uuid.UUID,
    db: DbSession,
    current_user: OptionalUser,
    page: int = 1,
    page_size: int = 20,
    sort: SortOrder = SortOrder.recent,
    difficulty: Optional[Difficulty] = None,
):
    opt_id = current_user.id if current_user else None
    await user_service.get_user_by_id(db, user_id)
    return await route_service.list_routes(
        db, page, page_size, region=None, difficulty=difficulty, user_id=opt_id,
        author_id=user_id, sort=sort,
    )


@router.get("/{user_id}/followers", response_model=PaginatedResponse[UserProfile])
async def get_followers(
    user_id: uuid.UUID,
    db: DbSession,
    current_user: OptionalUser,
    page: int = 1,
    page_size: int = 20,
):
    opt_id = current_user.id if current_user else None
    return await user_service.get_followers(db, user_id, opt_id, page, page_size)


@router.get("/{user_id}/following", response_model=PaginatedResponse[UserProfile])
async def get_following(
    user_id: uuid.UUID,
    db: DbSession,
    current_user: OptionalUser,
    page: int = 1,
    page_size: int = 20,
):
    opt_id = current_user.id if current_user else None
    return await user_service.get_following(db, user_id, opt_id, page, page_size)


@router.post("/{user_id}/follow", status_code=204)
async def follow(user_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await user_service.follow_user(db, current_user.id, user_id)


@router.delete("/{user_id}/follow", status_code=204)
async def unfollow(user_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await user_service.unfollow_user(db, current_user.id, user_id)
