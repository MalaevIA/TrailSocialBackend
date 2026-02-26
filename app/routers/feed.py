from fastapi import APIRouter

from app.dependencies import DbSession, CurrentUser, OptionalUser
from app.schemas.common import PaginatedResponse
from app.schemas.route import RouteResponse
from app.schemas.user import UserProfile
from app.services import feed_service

router = APIRouter(tags=["feed"])


@router.get("/feed", response_model=PaginatedResponse[RouteResponse])
async def get_feed(
    current_user: CurrentUser,
    db: DbSession,
    page: int = 1,
    page_size: int = 20,
):
    return await feed_service.get_feed(db, current_user.id, page, page_size)


@router.get("/search", response_model=PaginatedResponse[RouteResponse])
async def search(
    q: str,
    db: DbSession,
    current_user: OptionalUser,
    page: int = 1,
    page_size: int = 20,
):
    opt_id = current_user.id if current_user else None
    return await feed_service.search_routes(db, q, page, page_size, opt_id)


@router.get("/search/users", response_model=PaginatedResponse[UserProfile])
async def search_users(
    q: str,
    db: DbSession,
    current_user: OptionalUser,
    page: int = 1,
    page_size: int = 20,
):
    opt_id = current_user.id if current_user else None
    return await feed_service.search_users(db, q, page, page_size, opt_id)


@router.get("/regions", response_model=list[str])
async def get_regions(db: DbSession):
    return await feed_service.get_regions(db)
