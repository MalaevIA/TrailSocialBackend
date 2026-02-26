import uuid
from typing import Optional, List

from fastapi import APIRouter, Query

from app.dependencies import DbSession, CurrentUser, OptionalUser
from app.models.route import Difficulty
from app.schemas.common import PaginatedResponse
from app.schemas.route import RouteCreate, RouteUpdate, RouteResponse, SortOrder
from app.services import route_service

router = APIRouter(prefix="/routes", tags=["routes"])


@router.get("", response_model=PaginatedResponse[RouteResponse])
async def list_routes(
    db: DbSession,
    current_user: OptionalUser,
    page: int = 1,
    page_size: int = 20,
    region: Optional[str] = None,
    difficulty: Optional[Difficulty] = None,
    sort: SortOrder = SortOrder.recent,
    tags: Optional[List[str]] = Query(default=None, description="Теги через запятую или несколько параметров: ?tags=forest&tags=waterfall"),
    distance_min: Optional[float] = Query(default=None, ge=0),
    distance_max: Optional[float] = Query(default=None, ge=0),
):
    opt_id = current_user.id if current_user else None
    return await route_service.list_routes(
        db, page, page_size, region, difficulty, opt_id,
        sort=sort, tags=tags, distance_min=distance_min, distance_max=distance_max,
    )


@router.post("", response_model=RouteResponse, status_code=201)
async def create_route(data: RouteCreate, current_user: CurrentUser, db: DbSession):
    return await route_service.create_route(db, current_user.id, data)


@router.get("/{route_id}", response_model=RouteResponse)
async def get_route(route_id: uuid.UUID, db: DbSession, current_user: OptionalUser):
    opt_id = current_user.id if current_user else None
    return await route_service.get_route(db, route_id, opt_id)


@router.put("/{route_id}", response_model=RouteResponse)
async def update_route(
    route_id: uuid.UUID, data: RouteUpdate, current_user: CurrentUser, db: DbSession
):
    return await route_service.update_route(db, route_id, current_user.id, data)


@router.delete("/{route_id}", status_code=204)
async def delete_route(route_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await route_service.delete_route(db, route_id, current_user.id)


@router.post("/{route_id}/like", status_code=204)
async def like_route(route_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await route_service.like_route(db, route_id, current_user.id)


@router.delete("/{route_id}/like", status_code=204)
async def unlike_route(route_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await route_service.unlike_route(db, route_id, current_user.id)


@router.post("/{route_id}/save", status_code=204)
async def save_route(route_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await route_service.save_route(db, route_id, current_user.id)


@router.delete("/{route_id}/save", status_code=204)
async def unsave_route(route_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await route_service.unsave_route(db, route_id, current_user.id)
