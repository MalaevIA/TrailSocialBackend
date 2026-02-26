import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, Follow
from app.schemas.common import PaginatedResponse
from app.schemas.user import UpdateProfileRequest, UserPublic, UserProfile


async def _enrich_users(
    db: AsyncSession,
    users: list[User],
    current_user_id: Optional[uuid.UUID],
) -> list[UserProfile]:
    """Bulk-enrich a list of users with is_following flag. No N+1."""
    if not users:
        return []

    following_set: set[uuid.UUID] = set()
    if current_user_id:
        user_ids = [u.id for u in users]
        result = await db.execute(
            select(Follow.following_id).where(
                Follow.follower_id == current_user_id,
                Follow.following_id.in_(user_ids),
            )
        )
        following_set = {row for row in result.scalars().all()}

    enriched = []
    for user in users:
        profile = UserProfile.model_validate(user)
        profile.is_following = user.id in following_set
        enriched.append(profile)
    return enriched


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


async def get_user_profile(
    db: AsyncSession,
    user_id: uuid.UUID,
    current_user_id: uuid.UUID | None = None,
) -> UserProfile:
    user = await get_user_by_id(db, user_id)

    is_following = False
    if current_user_id:
        result = await db.execute(
            select(Follow).where(
                Follow.follower_id == current_user_id,
                Follow.following_id == user_id,
            )
        )
        is_following = result.scalar_one_or_none() is not None

    profile = UserProfile.model_validate(user)
    profile.is_following = is_following
    return profile


async def update_profile(
    db: AsyncSession,
    user: User,
    data: UpdateProfileRequest,
) -> User:
    update_data = data.model_dump(exclude_none=True)
    if not update_data:
        return user

    update_data["updated_at"] = datetime.now(timezone.utc)
    await db.execute(
        update(User).where(User.id == user.id).values(**update_data)
    )
    await db.flush()

    # Refresh in-memory object
    result = await db.execute(select(User).where(User.id == user.id))
    return result.scalar_one()


async def follow_user(
    db: AsyncSession,
    follower_id: uuid.UUID,
    following_id: uuid.UUID,
) -> None:
    if follower_id == following_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot follow yourself",
        )

    # Check target exists
    target = await get_user_by_id(db, following_id)

    # Check already following
    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == follower_id,
            Follow.following_id == following_id,
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Already following this user",
        )

    from app.models.notification import NotificationType
    from app.services.notification_service import create_notification

    follow = Follow(follower_id=follower_id, following_id=following_id)
    db.add(follow)

    # Atomic counter updates
    await db.execute(
        update(User)
        .where(User.id == follower_id)
        .values(following_count=User.following_count + 1)
    )
    await db.execute(
        update(User)
        .where(User.id == following_id)
        .values(followers_count=User.followers_count + 1)
    )
    await create_notification(
        db,
        recipient_id=following_id,
        actor_id=follower_id,
        type=NotificationType.new_follower,
    )
    await db.flush()


async def unfollow_user(
    db: AsyncSession,
    follower_id: uuid.UUID,
    following_id: uuid.UUID,
) -> None:
    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == follower_id,
            Follow.following_id == following_id,
        )
    )
    follow = result.scalar_one_or_none()
    if not follow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not following this user",
        )

    await db.delete(follow)

    # Atomic counter updates
    await db.execute(
        update(User)
        .where(User.id == follower_id)
        .values(following_count=User.following_count - 1)
    )
    await db.execute(
        update(User)
        .where(User.id == following_id)
        .values(followers_count=User.followers_count - 1)
    )
    await db.flush()


async def change_password(
    db: AsyncSession,
    user: User,
    current_password: str,
    new_password: str,
) -> None:
    from app.core.security import verify_password, hash_password

    if not verify_password(current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(
            hashed_password=hash_password(new_password),
            updated_at=datetime.now(timezone.utc),
        )
    )
    await db.flush()


async def get_followers(
    db: AsyncSession,
    user_id: uuid.UUID,
    current_user_id: Optional[uuid.UUID],
    page: int,
    page_size: int,
) -> PaginatedResponse[UserProfile]:
    await get_user_by_id(db, user_id)

    total_result = await db.execute(
        select(func.count()).select_from(Follow).where(Follow.following_id == user_id)
    )
    total = total_result.scalar_one()

    result = await db.execute(
        select(Follow.follower_id)
        .where(Follow.following_id == user_id)
        .order_by(Follow.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    follower_ids = result.scalars().all()

    users: list[User] = []
    if follower_ids:
        result = await db.execute(select(User).where(User.id.in_(follower_ids)))
        by_id = {u.id: u for u in result.scalars().all()}
        users = [by_id[fid] for fid in follower_ids if fid in by_id]

    items = await _enrich_users(db, users, current_user_id)
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if total else 0,
    )


async def get_following(
    db: AsyncSession,
    user_id: uuid.UUID,
    current_user_id: Optional[uuid.UUID],
    page: int,
    page_size: int,
) -> PaginatedResponse[UserProfile]:
    await get_user_by_id(db, user_id)

    total_result = await db.execute(
        select(func.count()).select_from(Follow).where(Follow.follower_id == user_id)
    )
    total = total_result.scalar_one()

    result = await db.execute(
        select(Follow.following_id)
        .where(Follow.follower_id == user_id)
        .order_by(Follow.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    following_ids = result.scalars().all()

    users: list[User] = []
    if following_ids:
        result = await db.execute(select(User).where(User.id.in_(following_ids)))
        by_id = {u.id: u for u in result.scalars().all()}
        users = [by_id[fid] for fid in following_ids if fid in by_id]

    items = await _enrich_users(db, users, current_user_id)
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if total else 0,
    )
