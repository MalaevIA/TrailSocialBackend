"""
Import popular hiking routes from OpenStreetMap (Overpass API) into the database.

Usage:
    .venv/bin/python scripts/import_osm_routes.py

Creates a system user "trail_explorer" as the author and imports up to 10 routes
from each of 10 popular hiking regions in Russia.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, text

# -- bootstrap app modules ---------------------------------------------------
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User
from app.models.route import TrailRoute, Difficulty, RouteStatus

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# 10 popular hiking regions: (name, south, west, north, east)
REGIONS = [
    ("Красная Поляна, Сочи",      43.5,  40.0,  43.75, 40.4),
    ("Кавказский заповедник",      43.85, 40.0,  44.1,  40.4),
    ("Крым, Южный берег",          44.35, 33.8,  44.6,  34.4),
    ("Алтай",                      50.0,  85.5,  51.5,  87.5),
    ("Приэльбрусье",               43.2,  42.3,  43.5,  42.8),
    ("Домбай, Карачаево-Черкесия", 43.2,  41.5,  43.4,  41.8),
    ("Байкал",                     51.5,  103.5, 53.5,  109.0),
    ("Хибины, Мурманская область", 67.5,  33.0,  67.9,  34.0),
    ("Урал, Таганай",              55.15, 59.7,  55.35, 59.9),
    ("Ладога, Карелия",            61.0,  30.5,  62.0,  31.5),
]

SAC_SCALE_MAP = {
    "hiking": Difficulty.easy,
    "mountain_hiking": Difficulty.moderate,
    "demanding_mountain_hiking": Difficulty.hard,
    "alpine_hiking": Difficulty.expert,
    "demanding_alpine_hiking": Difficulty.expert,
    "difficult_alpine_hiking": Difficulty.expert,
}

SYSTEM_USERNAME = "trail_explorer"
SYSTEM_EMAIL = "explorer@trail.social"
SYSTEM_DISPLAY_NAME = "Trail Explorer"


async def get_or_create_system_user(session) -> uuid.UUID:
    """Get or create the system user that will own imported routes."""
    result = await session.execute(
        select(User).where(User.username == SYSTEM_USERNAME)
    )
    user = result.scalar_one_or_none()
    if user:
        logger.info("System user exists: %s", user.id)
        return user.id

    user = User(
        id=uuid.uuid4(),
        username=SYSTEM_USERNAME,
        email=SYSTEM_EMAIL,
        hashed_password=hash_password("not-a-real-password-osm-import"),
        display_name=SYSTEM_DISPLAY_NAME,
        bio="Автоматический импорт маршрутов из OpenStreetMap",
        is_active=True,
        is_admin=False,
    )
    session.add(user)
    await session.flush()
    logger.info("Created system user: %s", user.id)
    return user.id


async def fetch_routes_for_region(
    client: httpx.AsyncClient,
    region_name: str,
    south: float,
    west: float,
    north: float,
    east: float,
    limit: int = 10,
) -> list[dict]:
    """Fetch hiking routes from Overpass API for a bounding box."""
    query = f"""
[out:json][timeout:60];
(
  relation["route"="hiking"]({south},{west},{north},{east});
  relation["route"="foot"]({south},{west},{north},{east});
);
out geom;
"""
    logger.info("Fetching routes for %s ...", region_name)
    try:
        resp = await client.post(OVERPASS_URL, data={"data": query})
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("Failed to fetch %s: %s", region_name, e)
        return []

    elements = data.get("elements", [])
    logger.info("  %s: got %d raw routes", region_name, len(elements))

    # Filter: must have name and geometry
    valid = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("name:ru")
        if not name:
            continue

        # Collect geometry from way members
        coords = _extract_geometry(el)
        if len(coords) < 2:
            continue

        valid.append({"element": el, "tags": tags, "name": name, "coords": coords})

    # Sort by number of coordinates (more detailed = better) and take top N
    valid.sort(key=lambda r: len(r["coords"]), reverse=True)
    selected = valid[:limit]
    logger.info("  %s: %d valid routes, selected %d", region_name, len(valid), len(selected))
    return selected


def _extract_geometry(element: dict) -> list[list[float]]:
    """Extract an ordered list of [lng, lat] from relation members."""
    coords = []
    for member in element.get("members", []):
        if member.get("type") == "way" and "geometry" in member:
            for pt in member["geometry"]:
                coords.append([pt["lon"], pt["lat"]])
    return coords


def _map_difficulty(tags: dict) -> Difficulty:
    sac = tags.get("sac_scale", "")
    return SAC_SCALE_MAP.get(sac, Difficulty.moderate)


def _estimate_duration(distance_km: float, difficulty: Difficulty) -> int:
    """Estimate duration in minutes based on distance and difficulty."""
    speed_map = {
        Difficulty.easy: 3.5,
        Difficulty.moderate: 3.0,
        Difficulty.hard: 2.5,
        Difficulty.expert: 2.0,
    }
    speed = speed_map[difficulty]
    return int((distance_km / speed) * 60)


def _build_tags(osm_tags: dict) -> list[str]:
    """Build app tags from OSM tags."""
    tags = []
    route_type = osm_tags.get("route", "hiking")
    if route_type == "hiking":
        tags.append("hiking")
    elif route_type == "foot":
        tags.append("walking")

    if osm_tags.get("roundtrip") == "yes":
        tags.append("circular")

    network = osm_tags.get("network", "")
    if network == "nwn":
        tags.append("national")
    elif network == "rwn":
        tags.append("regional")
    elif network == "lwn":
        tags.append("local")

    if osm_tags.get("sac_scale"):
        tags.append("mountain")

    tags.append("osm-import")
    return tags


def _build_waypoints(coords: list[list[float]], name: str) -> list[dict]:
    """Build waypoints: start, midpoint(s), end."""
    waypoints = []
    waypoints.append({
        "lat": coords[0][1],
        "lng": coords[0][0],
        "name": f"Начало: {name}",
        "description": "Начальная точка маршрута",
    })

    if len(coords) >= 4:
        mid = len(coords) // 2
        waypoints.append({
            "lat": coords[mid][1],
            "lng": coords[mid][0],
            "name": "Середина маршрута",
            "description": None,
        })

    waypoints.append({
        "lat": coords[-1][1],
        "lng": coords[-1][0],
        "name": f"Конец: {name}",
        "description": "Конечная точка маршрута",
    })
    return waypoints


def _haversine_distance(coords: list[list[float]]) -> float:
    """Calculate total distance in km from a list of [lng, lat] coordinates."""
    import math
    total = 0.0
    R = 6371.0
    for i in range(len(coords) - 1):
        lon1, lat1 = math.radians(coords[i][0]), math.radians(coords[i][1])
        lon2, lat2 = math.radians(coords[i + 1][0]), math.radians(coords[i + 1][1])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        total += R * 2 * math.asin(math.sqrt(a))
    return round(total, 2)


async def import_routes():
    """Main import routine."""
    async with httpx.AsyncClient(timeout=90.0) as client:
        all_routes = []
        for region_name, south, west, north, east in REGIONS:
            routes = await fetch_routes_for_region(
                client, region_name, south, west, north, east, limit=10,
            )
            for r in routes:
                r["region_name"] = region_name
            all_routes.extend(routes)
            # Be polite to Overpass API — avoid 429
            await asyncio.sleep(15)

    logger.info("Total routes to import: %d", len(all_routes))

    if not all_routes:
        logger.warning("No routes found, exiting")
        return

    async with AsyncSessionLocal() as session:
        async with session.begin():
            author_id = await get_or_create_system_user(session)

            imported = 0
            skipped = 0
            for route_data in all_routes:
                tags = route_data["tags"]
                name = route_data["name"]
                coords = route_data["coords"]
                region = route_data["region_name"]

                # Check for duplicate by title + region
                existing = await session.execute(
                    select(TrailRoute).where(
                        TrailRoute.title == name,
                        TrailRoute.region == region,
                    )
                )
                if existing.scalar_one_or_none():
                    skipped += 1
                    continue

                difficulty = _map_difficulty(tags)

                # Distance from OSM tags or calculate from geometry
                distance_str = tags.get("distance", "")
                try:
                    distance_km = float(distance_str)
                except (ValueError, TypeError):
                    distance_km = _haversine_distance(coords)

                duration = _estimate_duration(distance_km, difficulty)
                app_tags = _build_tags(tags)
                waypoints = _build_waypoints(coords, name)

                geometry = {
                    "type": "LineString",
                    "coordinates": coords,
                }

                description = tags.get("description", "")
                if not description:
                    description = f"Маршрут «{name}» в регионе {region}. Импортировано из OpenStreetMap."

                route = TrailRoute(
                    id=uuid.uuid4(),
                    author_id=author_id,
                    status=RouteStatus.published,
                    title=name,
                    description=description,
                    region=region,
                    distance_km=distance_km,
                    elevation_gain_m=None,
                    duration_minutes=duration,
                    difficulty=difficulty,
                    tags=app_tags,
                    start_lat=coords[0][1],
                    start_lng=coords[0][0],
                    end_lat=coords[-1][1],
                    end_lng=coords[-1][0],
                    geometry=geometry,
                    waypoints=waypoints,
                    photos=None,
                )
                session.add(route)
                imported += 1

            # Update routes_count for system user
            if imported > 0:
                await session.execute(
                    text("UPDATE users SET routes_count = routes_count + :cnt WHERE id = :uid"),
                    {"cnt": imported, "uid": author_id},
                )

            logger.info("Imported: %d, Skipped (duplicates): %d", imported, skipped)


if __name__ == "__main__":
    asyncio.run(import_routes())
