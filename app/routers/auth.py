from fastapi import APIRouter, Request

from app.core.limiter import limiter
from app.dependencies import DbSession
from app.schemas.auth import SignupRequest, LoginRequest, RefreshRequest, LogoutRequest, TokenResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse, status_code=201)
@limiter.limit("5/minute")
async def signup(request: Request, data: SignupRequest, db: DbSession):
    return await auth_service.signup(db, data)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, data: LoginRequest, db: DbSession):
    return await auth_service.login(db, data)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("30/minute")
async def refresh(request: Request, data: RefreshRequest, db: DbSession):
    return await auth_service.refresh_tokens(db, data.refresh_token)


@router.post("/logout", status_code=204)
async def logout(data: LogoutRequest, db: DbSession):
    await auth_service.logout(db, data.refresh_token)
