from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.models.token_blacklist import TokenBlacklist
from app.models.user import User
from app.schemas.auth import SignupRequest, LoginRequest, TokenResponse


async def _is_blacklisted(db: AsyncSession, jti: str) -> bool:
    result = await db.execute(
        select(TokenBlacklist).where(TokenBlacklist.jti == jti)
    )
    return result.scalar_one_or_none() is not None


async def _blacklist_jti(db: AsyncSession, jti: str) -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    db.add(TokenBlacklist(jti=jti, expires_at=expires_at))


async def signup(db: AsyncSession, data: SignupRequest) -> TokenResponse:
    result = await db.execute(select(User).where(User.username == data.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")

    result = await db.execute(select(User).where(User.email == data.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        username=data.username,
        email=data.email,
        hashed_password=hash_password(data.password),
        display_name=data.display_name,
    )
    db.add(user)
    await db.flush()

    refresh_token, _ = create_refresh_token(str(user.id))
    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=refresh_token,
    )


async def login(db: AsyncSession, data: LoginRequest) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")

    refresh_token, _ = create_refresh_token(str(user.id))
    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=refresh_token,
    )


async def refresh_tokens(db: AsyncSession, refresh_token: str) -> TokenResponse:
    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    jti = payload.get("jti")
    if not jti:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token format",
        )

    # Если JTI уже в блэклисте — токен украден или повторно использован
    if await _is_blacklisted(db, jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has already been used or revoked",
        )

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # Rotation: старый JTI → в блэклист, выдаём новую пару токенов
    await _blacklist_jti(db, jti)
    new_refresh_token, _ = create_refresh_token(str(user.id))
    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=new_refresh_token,
    )


async def logout(db: AsyncSession, refresh_token: str) -> None:
    payload = decode_token(refresh_token)
    # Если токен невалидный или уже истёк — просто игнорируем
    if not payload or payload.get("type") != "refresh":
        return
    jti = payload.get("jti")
    if jti and not await _is_blacklisted(db, jti):
        await _blacklist_jti(db, jti)


async def cleanup_expired_tokens(db: AsyncSession) -> int:
    """Удаляет истёкшие записи из блэклиста. Вызывать по расписанию."""
    result = await db.execute(
        delete(TokenBlacklist).where(
            TokenBlacklist.expires_at < datetime.now(timezone.utc)
        )
    )
    return result.rowcount
