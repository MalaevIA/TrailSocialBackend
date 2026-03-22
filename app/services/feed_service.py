import logging
import uuid
from pathlib import Path
from typing import Optional

import httpx
from sqlalchemy import select, func, and_, update, literal
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.route import TrailRoute, RouteStatus
from app.models.user import Follow, User
from app.schemas.common import PaginatedResponse
from app.schemas.route import RegionInfo, RouteResponse
from app.schemas.user import UserProfile
from app.services.route_service import _enrich_routes
from app.services.user_service import _enrich_users

logger = logging.getLogger(__name__)

WIKIMEDIA_API_URL = "https://commons.wikimedia.org/w/api.php"
WIKIMEDIA_UA = "TrailSocialApp/1.0 (https://github.com/trailsocial; trailsocial@example.com) python-httpx/0.28"


async def get_feed(
    db: AsyncSession,
    user_id: uuid.UUID,
    page: int,
    page_size: int,
) -> PaginatedResponse[RouteResponse]:
    # Subquery: IDs of users I follow
    followed_subq = (
        select(Follow.following_id).where(Follow.follower_id == user_id).scalar_subquery()
    )

    base_filter = and_(
        TrailRoute.author_id.in_(followed_subq),
        TrailRoute.status == RouteStatus.published,
    )

    total_result = await db.execute(
        select(func.count()).select_from(TrailRoute).where(base_filter)
    )
    total = total_result.scalar_one()

    result = await db.execute(
        select(TrailRoute)
        .where(base_filter)
        .order_by(TrailRoute.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    routes = result.scalars().all()

    items = await _enrich_routes(db, list(routes), user_id)
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if total else 0,
    )


async def search_routes(
    db: AsyncSession,
    q: str,
    page: int,
    page_size: int,
    user_id: Optional[uuid.UUID],
) -> PaginatedResponse[RouteResponse]:
    pattern = f"%{q}%"
    base_filter = and_(
        TrailRoute.title.ilike(pattern) | TrailRoute.description.ilike(pattern),
        TrailRoute.status == RouteStatus.published,
    )

    total_result = await db.execute(
        select(func.count()).select_from(TrailRoute).where(base_filter)
    )
    total = total_result.scalar_one()

    result = await db.execute(
        select(TrailRoute)
        .where(base_filter)
        .order_by(TrailRoute.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    routes = result.scalars().all()

    items = await _enrich_routes(db, list(routes), user_id)
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if total else 0,
    )


async def get_regions(db: AsyncSession) -> list[RegionInfo]:
    # Count published routes per region + pick first photo
    result = await db.execute(
        select(
            TrailRoute.region,
            func.count().label("route_count"),
            func.min(TrailRoute.photos[1]).label("photo_url"),
        )
        .where(
            TrailRoute.region.isnot(None),
            TrailRoute.status == RouteStatus.published,
        )
        .group_by(TrailRoute.region)
        .order_by(func.count().desc())
    )
    rows = result.all()

    regions = []
    regions_need_photo: list[str] = []

    for row in rows:
        regions.append(
            RegionInfo(name=row.region, route_count=row.route_count, photo_url=row.photo_url)
        )
        if not row.photo_url:
            regions_need_photo.append(row.region)

    # For regions without photos — fetch from Wikimedia, save to uploads & DB
    if regions_need_photo:
        await _fill_missing_region_photos(db, regions, regions_need_photo)

    return regions


async def _fill_missing_region_photos(
    db: AsyncSession,
    regions: list[RegionInfo],
    region_names: list[str],
) -> None:
    """Fetch photos from Wikimedia for regions that have no photo,
    download to uploads/, save URL to the route in DB."""
    # Get one route per region to use its coordinates
    for region_name in region_names:
        try:
            route_result = await db.execute(
                select(TrailRoute.id, TrailRoute.start_lat, TrailRoute.start_lng)
                .where(
                    TrailRoute.region == region_name,
                    TrailRoute.status == RouteStatus.published,
                )
                .limit(1)
            )
            route_row = route_result.first()
            if not route_row:
                continue

            route_id, lat, lng = route_row.id, route_row.start_lat, route_row.start_lng

            # Search Wikimedia Commons near the route start
            photo_url = await _fetch_and_save_wikimedia_photo(lat, lng)
            if not photo_url:
                continue

            # Save photo to this route in DB (set as single-element array)
            await db.execute(
                update(TrailRoute)
                .where(TrailRoute.id == route_id)
                .values(photos=[photo_url])
            )
            await db.commit()

            # Update the RegionInfo in our result list
            for r in regions:
                if r.name == region_name:
                    r.photo_url = photo_url
                    break

        except Exception as e:
            logger.error("Failed to fetch photo for region '%s': %s", region_name, e)


async def _fetch_and_save_wikimedia_photo(lat: float, lng: float) -> Optional[str]:
    """Fetch a photo from Wikimedia Commons near coordinates,
    download it to uploads/, return local URL."""
    import asyncio as _asyncio

    try:
        # Step 1: Search for images via API (httpx works fine for API calls)
        async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": WIKIMEDIA_UA}) as client:
            resp = await client.get(WIKIMEDIA_API_URL, params={
                "action": "query",
                "generator": "geosearch",
                "ggscoord": f"{lat}|{lng}",
                "ggsradius": 10000,  # 10km radius for region cover photo
                "ggsnamespace": 6,
                "ggslimit": 5,
                "prop": "imageinfo",
                "iiprop": "url|mime",
                "iiurlwidth": 1200,
                "format": "json",
            })
            resp.raise_for_status()
            data = resp.json()

        pages = data.get("query", {}).get("pages", {})
        if not pages:
            return None

        # Pick first valid image — prefer thumburl (smaller), fallback to original
        image_url = None
        for page in pages.values():
            imageinfo = page.get("imageinfo", [])
            if not imageinfo:
                continue
            info = imageinfo[0]
            mime = info.get("mime", "")
            if mime.startswith("image/"):
                image_url = info.get("thumburl") or info.get("url")
                break

        if not image_url:
            return None

        # Step 2: Download via curl (Wikimedia blocks httpx on upload.wikimedia.org)
        ext = "jpg"
        if ".png" in image_url.lower():
            ext = "png"
        elif ".webp" in image_url.lower():
            ext = "webp"

        filename = f"{uuid.uuid4()}.{ext}"
        upload_dir = Path(settings.UPLOAD_DIR)
        upload_dir.mkdir(parents=True, exist_ok=True)
        filepath = upload_dir / filename

        proc = await _asyncio.create_subprocess_exec(
            "curl", "-sL", "-o", str(filepath),
            "-w", "%{http_code}",
            "--max-filesize", "5242880",  # 5 MB limit
            "--max-time", "10",
            image_url,
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        http_code = stdout.decode().strip()

        if http_code != "200" or not filepath.exists() or filepath.stat().st_size < 1000:
            filepath.unlink(missing_ok=True)
            logger.warning("curl download failed for %s: HTTP %s", image_url[:80], http_code)
            return None

        local_url = f"/uploads/{filename}"
        logger.info("Downloaded region photo: %s -> %s", image_url[:80], local_url)
        return local_url

    except Exception as e:
        logger.error("Failed to download Wikimedia photo for (%.4f, %.4f): %s", lat, lng, e)
        return None


async def search_users(
    db: AsyncSession,
    q: str,
    page: int,
    page_size: int,
    current_user_id: Optional[uuid.UUID],
) -> PaginatedResponse[UserProfile]:
    pattern = f"%{q}%"
    base_filter = User.username.ilike(pattern) | User.display_name.ilike(pattern)

    total_result = await db.execute(
        select(func.count()).select_from(User).where(base_filter)
    )
    total = total_result.scalar_one()

    result = await db.execute(
        select(User)
        .where(base_filter)
        .order_by(User.followers_count.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    users = result.scalars().all()

    items = await _enrich_users(db, list(users), current_user_id)
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if total else 0,
    )
