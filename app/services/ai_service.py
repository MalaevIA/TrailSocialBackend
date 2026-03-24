import asyncio
import json
import logging
import math
import uuid
from dataclasses import dataclass
from typing import Optional, TypeVar, Callable, Awaitable

import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.schemas.ai import RouteBuilderForm, GeneratedRoute

logger = logging.getLogger(__name__)

YANDEX_GPT_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
YANDEX_OPENAI_URL = "https://llm.api.cloud.yandex.net/v1/chat/completions"
YANDEX_GEOCODER_URL = "https://geocode-maps.yandex.ru/1.x/"
OSRM_ROUTE_URL = "https://router.project-osrm.org/route/v1/foot"

T = TypeVar("T")

_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF = 1.5  # секунды между попытками


async def _with_retry(
    fn: Callable[[], Awaitable[T]],
    attempts: int = _RETRY_ATTEMPTS,
    backoff: float = _RETRY_BACKOFF,
    label: str = "",
) -> T:
    """Повторяет fn до attempts раз при httpx.HTTPError или TimeoutException."""
    last_exc: Exception = RuntimeError("No attempts made")
    for attempt in range(1, attempts + 1):
        try:
            return await fn()
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            last_exc = e
            if attempt < attempts:
                wait = backoff * attempt
                logger.warning("%s: attempt %d/%d failed (%s), retrying in %.1fs", label, attempt, attempts, e, wait)
                await asyncio.sleep(wait)
            else:
                logger.error("%s: all %d attempts failed: %s", label, attempts, e)
    raise last_exc

# Models that require OpenAI-compatible API instead of gRPC
OPENAI_COMPAT_MODELS = {"qwen3-235b-a22b-fp8", "deepseek-v32", "gemma-3-27b-it", "gpt-oss-120b", "gpt-oss-20b"}

SYSTEM_PROMPT = """Ты — помощник для приложения Trail Social. Твоя задача — предложить маршрут для прогулки/похода на основе предпочтений пользователя.

## Важно

Ты НЕ генерируешь координаты. Координаты будут получены автоматически через геокодер.
Вместо координат ты указываешь **точные адреса реальных мест**.

## Правила для waypoints (КРИТИЧЕСКИ ВАЖНО)

Waypoints — это ключевые точки маршрута (начало, интересные места, конец). Минимум 3, максимум 8.

Каждый waypoint.name — это ТОЧНЫЙ АДРЕС для геокодера. Геокодер ищет по всему миру, поэтому без точного адреса он найдёт ДРУГОЕ место!

Формат name: "<Объект>, <Улица/Район>, <Город>, <Область/Регион>, Россия"

Примеры ПРАВИЛЬНЫХ name:
- "Парк Зарядье, улица Варварка, Москва, Россия"
- "Центральный вход в парк Горького, Крымский Вал 9, Москва, Россия"
- "Приют Гремучий ключ, национальный парк Таганай, Златоуст, Челябинская область, Россия"
- "Водопад Поликаря, Красная Поляна, Сочи, Краснодарский край, Россия"
- "Станция канатной дороги Роза Хутор, Эстосадок, Сочи, Краснодарский край, Россия"
- "Озеро Тургояк, посёлок Тургояк, Миасс, Челябинская область, Россия"

Примеры НЕПРАВИЛЬНЫХ name (ЗАПРЕЩЕНО):
- "Красная площадь" — нет города, найдёт другой город
- "Озеро Тургояк" — нет района/области, найдёт однофамильца
- "Начало маршрута" — это не адрес
- "Смотровая площадка" — нет привязки к месту
- "Парк Горького" — без улицы/города, есть во многих городах

## Остальные правила

1. Предлагай ТОЛЬКО реально существующие места в указанном регионе.
2. Набор высоты должен соответствовать сложности и рельефу региона.
3. Длительность и дистанция должны быть согласованы:
   - easy: 3–4 км/ч
   - moderate: 2.5–3.5 км/ч
   - hard: 2–3 км/ч
   - expert: 1.5–2.5 км/ч
4. Весь текст — на русском языке.

## Формат ответа

Отвечай ТОЛЬКО валидным JSON. Никакого markdown, объяснений или лишнего текста.

{
  "title": "string — короткое, запоминающееся название маршрута",
  "description": "string — 2-3 предложения о маршруте, пейзажах и впечатлениях",
  "region": "string — название региона",
  "distance_km": number,
  "elevation_gain_m": number,
  "duration_minutes": integer,
  "difficulty": "easy | moderate | hard | expert",
  "tags": ["string", ...],
  "highlights": ["string", "string", "string"],
  "tips": ["string", "string", "string", "string"],
  "waypoints": [
    {"name": "string — ТОЧНЫЙ АДРЕС: Объект, Улица, Город, Область, Россия", "description": "string или null"}
  ]
}"""


def _build_user_prompt(form: RouteBuilderForm) -> str:
    parts = ["Сгенерируй маршрут со следующими параметрами:"]
    if form.region:
        parts.append(f"- Регион: {form.region}")
    if form.difficulty:
        parts.append(f"- Сложность: {form.difficulty.value}")
    if form.duration_minutes:
        parts.append(f"- Длительность: {form.duration_minutes} минут")
    if form.distance_km:
        parts.append(f"- Дистанция: {form.distance_km} км")
    if form.interests:
        parts.append(f"- Интересы: {', '.join(form.interests)}")
    if form.description:
        parts.append(f"- Описание: {form.description}")
    return "\n".join(parts)


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.index("\n")
        last_backticks = text.rfind("```")
        text = text[first_newline + 1:last_backticks].strip()
    return json.loads(text)


def _is_openai_compat(model: str) -> bool:
    model_base = model.split("/")[0]
    return model_base in OPENAI_COMPAT_MODELS


# ---------------------------------------------------------------------------
# Geocoding (Yandex Geocoder API)
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate distance in km between two points using Haversine formula."""
    R = 6371.0
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


async def _geocode(
    client: httpx.AsyncClient,
    place_name: str,
    center: Optional[tuple[float, float]] = None,
    spn: str = "2.0,2.0",
) -> Optional[tuple[float, float]]:
    """Geocode a place name → (lat, lng) using Yandex Geocoder.

    If center (lat, lng) is provided, biases results toward that location.
    spn controls the search area size (default "2.0,2.0" ≈ 200km).
    """
    try:
        params = {
            "apikey": settings.YANDEX_GEOCODER_API_KEY,
            "geocode": place_name,
            "format": "json",
            "results": 1,
        }
        if center is not None:
            lat, lng = center
            params["ll"] = f"{lng},{lat}"
            params["spn"] = spn
            params["rspn"] = "1"

        async def _do_geocode():
            resp = await client.get(YANDEX_GEOCODER_URL, params=params)
            resp.raise_for_status()
            return resp.json()

        data = await _with_retry(_do_geocode, label=f"Geocoder({place_name})")
        members = data["response"]["GeoObjectCollection"]["featureMember"]
        if not members:
            logger.warning("Geocoder: no results for '%s'", place_name)
            return None
        pos = members[0]["GeoObject"]["Point"]["pos"]  # "lng lat"
        lng_str, lat_str = pos.split()
        return float(lat_str), float(lng_str)
    except Exception as e:
        logger.error("Geocoding failed for '%s': %s", place_name, e)
        return None


async def _geocode_waypoints(
    client: httpx.AsyncClient,
    waypoints: list[dict],
    region: Optional[str] = None,
    expected_distance_km: Optional[float] = None,
) -> list[dict]:
    """Geocode all waypoints, then detect and fix outliers via re-geocoding.

    1. Geocode the first waypoint (optionally biased by region name).
    2. Use the first waypoint's coordinates as center for the rest.
    3. Detect outliers and try to fix them with tighter geocoder bias.
    """
    if not waypoints:
        return []

    # Step 1: geocode first waypoint to establish region center
    first_query = waypoints[0]["name"]
    if region:
        first_query = f"{first_query}, {region}"
    first_coords = await _geocode(client, first_query)
    center = first_coords  # may be None

    # Step 2: geocode remaining waypoints biased toward center
    tasks = [_geocode(client, wp["name"], center=center) for wp in waypoints[1:]]
    results = await asyncio.gather(*tasks)

    geocoded = []
    if first_coords is not None:
        geocoded.append({**waypoints[0], "lat": first_coords[0], "lng": first_coords[1]})
    for wp, coords in zip(waypoints[1:], results):
        if coords is not None:
            geocoded.append({**wp, "lat": coords[0], "lng": coords[1]})
        else:
            logger.warning("Skipping waypoint '%s' — geocoding failed", wp["name"])

    # Step 3: detect outliers and try to fix them with tighter geocoder bias
    if len(geocoded) >= 2:
        geocoded = await _fix_outlier_waypoints(client, geocoded, region, expected_distance_km)

    # Step 4: fix consecutive gaps > 10 km by asking AI to refine or insert waypoints
    if len(geocoded) >= 2:
        geocoded = await _fix_consecutive_gaps(client, geocoded)

    return geocoded


# Default max distance from median center (km) — used when route distance is unknown
DEFAULT_MAX_SPREAD_KM = 5.0


def _get_median_center(waypoints: list[dict]) -> tuple[float, float]:
    """Calculate the median center of a list of waypoints."""
    lats = sorted(wp["lat"] for wp in waypoints)
    lngs = sorted(wp["lng"] for wp in waypoints)
    return lats[len(lats) // 2], lngs[len(lngs) // 2]


async def _fix_outlier_waypoints(
    client: httpx.AsyncClient,
    waypoints: list[dict],
    region: Optional[str],
    expected_distance_km: Optional[float],
) -> list[dict]:
    """Detect waypoints that are too far from the group and re-geocode them.

    Threshold = max(5, expected_distance_km) if distance is known, else 5 km.
    For outliers: re-geocode with region suffix and tight spn (0.1° ≈ 10km).
    If still an outlier — remove.
    """
    max_spread = DEFAULT_MAX_SPREAD_KM
    if expected_distance_km and expected_distance_km > DEFAULT_MAX_SPREAD_KM:
        max_spread = expected_distance_km

    center_lat, center_lng = _get_median_center(waypoints)

    result = []
    for wp in waypoints:
        dist = _haversine_km(center_lat, center_lng, wp["lat"], wp["lng"])
        if dist <= max_spread:
            result.append(wp)
            continue

        # Outlier detected — try re-geocoding with region context and tight bias
        logger.info(
            "Outlier '%s': %.1f km from center (max %.1f km), re-geocoding...",
            wp["name"], dist, max_spread,
        )
        query = wp["name"]
        if region and region.lower() not in query.lower():
            query = f"{query}, {region}"

        new_coords = await _geocode(
            client, query, center=(center_lat, center_lng), spn="0.1,0.1",
        )
        if new_coords:
            new_dist = _haversine_km(center_lat, center_lng, new_coords[0], new_coords[1])
            if new_dist <= max_spread:
                wp["lat"] = new_coords[0]
                wp["lng"] = new_coords[1]
                result.append(wp)
                logger.info(
                    "Re-geocoded '%s': %.1f km -> %.1f km from center",
                    wp["name"], dist, new_dist,
                )
                continue
            else:
                logger.warning(
                    "Re-geocoded '%s' still too far: %.1f km (max %.1f km), removing",
                    wp["name"], new_dist, max_spread,
                )
        else:
            logger.warning("Re-geocoding failed for '%s', removing", wp["name"])

    return result


# ---------------------------------------------------------------------------
# Consecutive gap fix: если две соседние точки дальше 10 км — просим AI уточнить
# ---------------------------------------------------------------------------

_MAX_CONSECUTIVE_GAP_KM = 10.0
_MAX_GAP_FIX_ATTEMPTS = 5

_GAP_FIX_PROMPT = """\
Ты помогаешь уточнить маршрут. Проблема: точка "{current}" находится слишком далеко от предыдущей точки "{previous}" (расстояние {dist:.1f} км, допустимо не более 10 км).

Предложи одно из двух решения в JSON:
1. Более точный адрес для "{current}" — ближе к "{previous}":
   {{"action": "fix", "name": "точный адрес"}}
2. Промежуточную точку между "{previous}" и "{current}":
   {{"action": "insert", "name": "промежуточная точка"}}

Верни только JSON без пояснений."""


async def _ask_ai_fix_gap(previous_name: str, current_name: str, dist_km: float) -> Optional[dict]:
    """Просит AI уточнить точку или добавить промежуточную."""
    prompt = _GAP_FIX_PROMPT.format(
        previous=previous_name,
        current=current_name,
        dist=dist_km,
    )
    try:
        result = await _call_llm(prompt)
        action = result.get("action")
        name = result.get("name", "").strip()
        if action in ("fix", "insert") and name:
            return {"action": action, "name": name}
    except Exception as e:
        logger.warning("AI gap fix failed: %s", e)
    return None


async def _fix_consecutive_gaps(
    client: httpx.AsyncClient,
    waypoints: list[dict],
) -> list[dict]:
    """Проверяет последовательные расстояния между точками.

    Если расстояние между соседними точками > 10 км — просит AI уточнить адрес
    или добавить промежуточную точку. До 5 попыток на каждую проблемную точку.
    Если после всех попыток разрыв остаётся — точка удаляется.
    """
    if len(waypoints) < 2:
        return waypoints

    result = [waypoints[0]]

    i = 1
    while i < len(waypoints):
        prev = result[-1]
        curr = waypoints[i]
        dist = _haversine_km(prev["lat"], prev["lng"], curr["lat"], curr["lng"])

        if dist <= _MAX_CONSECUTIVE_GAP_KM:
            result.append(curr)
            i += 1
            continue

        logger.info(
            "Gap %.1f km between '%s' and '%s', asking AI to fix (max %d attempts)",
            dist, prev["name"], curr["name"], _MAX_GAP_FIX_ATTEMPTS,
        )

        fixed = False
        for attempt in range(1, _MAX_GAP_FIX_ATTEMPTS + 1):
            ai_fix = await _ask_ai_fix_gap(prev["name"], curr["name"], dist)
            if not ai_fix:
                logger.warning("Attempt %d/%d: AI returned nothing, skipping", attempt, _MAX_GAP_FIX_ATTEMPTS)
                continue

            center = (prev["lat"], prev["lng"])
            new_coords = await _geocode(client, ai_fix["name"], center=center, spn="0.2,0.2")
            if not new_coords:
                logger.warning("Attempt %d/%d: geocoding '%s' failed", attempt, _MAX_GAP_FIX_ATTEMPTS, ai_fix["name"])
                continue

            new_dist = _haversine_km(prev["lat"], prev["lng"], new_coords[0], new_coords[1])

            if ai_fix["action"] == "insert":
                # Вставляем промежуточную точку и перепроверяем curr на следующей итерации
                mid_wp = {"name": ai_fix["name"], "lat": new_coords[0], "lng": new_coords[1]}
                if new_dist <= _MAX_CONSECUTIVE_GAP_KM:
                    result.append(mid_wp)
                    logger.info(
                        "Attempt %d/%d: inserted '%s' (%.1f km from prev)",
                        attempt, _MAX_GAP_FIX_ATTEMPTS, ai_fix["name"], new_dist,
                    )
                    fixed = True
                    break
                else:
                    logger.warning(
                        "Attempt %d/%d: intermediate '%s' still %.1f km away",
                        attempt, _MAX_GAP_FIX_ATTEMPTS, ai_fix["name"], new_dist,
                    )

            else:  # action == "fix"
                if new_dist <= _MAX_CONSECUTIVE_GAP_KM:
                    curr = {**curr, "name": ai_fix["name"], "lat": new_coords[0], "lng": new_coords[1]}
                    result.append(curr)
                    logger.info(
                        "Attempt %d/%d: fixed '%s' → '%s' (%.1f km from prev)",
                        attempt, _MAX_GAP_FIX_ATTEMPTS, waypoints[i]["name"], ai_fix["name"], new_dist,
                    )
                    fixed = True
                    break
                else:
                    logger.warning(
                        "Attempt %d/%d: fixed '%s' → '%s' still %.1f km away",
                        attempt, _MAX_GAP_FIX_ATTEMPTS, curr["name"], ai_fix["name"], new_dist,
                    )

        if not fixed:
            logger.warning(
                "Dropping waypoint '%s' after %d attempts (gap %.1f km)",
                waypoints[i]["name"], _MAX_GAP_FIX_ATTEMPTS, dist,
            )

        i += 1

    return result


# ---------------------------------------------------------------------------
# Routing (OSRM — пеший маршрут)
# ---------------------------------------------------------------------------

async def _build_route_geometry(
    client: httpx.AsyncClient,
    waypoints: list[dict],
) -> Optional[dict]:
    """Build a walking route through waypoints using OSRM, returns GeoJSON LineString."""
    if len(waypoints) < 2:
        return None

    coords_str = ";".join(f"{wp['lng']},{wp['lat']}" for wp in waypoints)
    url = f"{OSRM_ROUTE_URL}/{coords_str}"

    try:
        osrm_params = {"overview": "full", "geometries": "geojson"}

        async def _do_osrm():
            resp = await client.get(url, params=osrm_params)
            resp.raise_for_status()
            return resp.json()

        data = await _with_retry(_do_osrm, label="OSRM")

        if data.get("code") != "Ok" or not data.get("routes"):
            logger.error("OSRM error: %s", data.get("code"))
            return None

        geometry = data["routes"][0]["geometry"]
        return {
            "type": "LineString",
            "coordinates": geometry["coordinates"],
        }
    except Exception as e:
        logger.error("OSRM routing failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Photo fetching from Wikimedia Commons by waypoint coordinates
# ---------------------------------------------------------------------------

WIKIMEDIA_API_URL = "https://commons.wikimedia.org/w/api.php"
WIKIMEDIA_SEARCH_RADIUS = 500  # meters


async def _fetch_photos_near(
    client: httpx.AsyncClient,
    lat: float,
    lng: float,
) -> list[str]:
    """Fetch photo URLs from Wikimedia Commons near a coordinate (500m radius)."""
    try:
        # Step 1: find images geotagged near the coordinate
        resp = await client.get(WIKIMEDIA_API_URL, params={
            "action": "query",
            "generator": "geosearch",
            "ggscoord": f"{lat}|{lng}",
            "ggsradius": WIKIMEDIA_SEARCH_RADIUS,
            "ggsnamespace": 6,  # File namespace
            "ggslimit": _MAX_PHOTOS_PER_WAYPOINT,
            "prop": "imageinfo",
            "iiprop": "url|mime",
            "iiurlwidth": 1200,
            "format": "json",
        })
        resp.raise_for_status()
        data = resp.json()

        pages = data.get("query", {}).get("pages", {})
        if not pages:
            return []

        urls = []
        for page in pages.values():
            imageinfo = page.get("imageinfo", [])
            if not imageinfo:
                continue
            info = imageinfo[0]
            mime = info.get("mime", "")
            if not mime.startswith("image/"):
                continue
            # Prefer thumbnail (1200px wide) over original
            url = info.get("thumburl") or info.get("url")
            if url:
                urls.append(url)
        return urls
    except Exception as e:
        logger.error("Wikimedia photo fetch failed for (%.4f, %.4f): %s", lat, lng, e)
        return []


_MAX_PHOTOS_PER_WAYPOINT = 2
_MAX_PHOTOS_TOTAL = 20


async def _fetch_photos_for_waypoints(
    waypoints: list[dict],
) -> list[str]:
    """Fetch photos from Wikimedia Commons for all waypoints in parallel.

    Не более _MAX_PHOTOS_PER_WAYPOINT фото на одну точку,
    не более _MAX_PHOTOS_TOTAL фото суммарно.
    """
    if not waypoints:
        return []

    async with httpx.AsyncClient(timeout=15.0, headers={
        "User-Agent": "TrailSocialApp/1.0 (https://github.com/trailsocial; trailsocial@example.com) python-httpx/0.28",
    }) as client:
        tasks = [_fetch_photos_near(client, wp["lat"], wp["lng"]) for wp in waypoints]
        results = await asyncio.gather(*tasks)

    seen: set[str] = set()
    photos: list[str] = []
    for photo_list in results:
        taken = 0
        for url in photo_list:
            if taken >= _MAX_PHOTOS_PER_WAYPOINT:
                break
            if url not in seen:
                seen.add(url)
                photos.append(url)
                taken += 1
                if len(photos) >= _MAX_PHOTOS_TOTAL:
                    return photos
    return photos


# ---------------------------------------------------------------------------
# Task management (Redis)
# ---------------------------------------------------------------------------

_TASK_TTL = 3600  # задачи живут 1 час
_TASK_PREFIX = "ai_task:"


@dataclass
class _Task:
    status: str = "pending"  # pending | completed | failed
    result: Optional[GeneratedRoute] = None
    error: Optional[str] = None


async def _save_task(task_id: str, task: _Task) -> None:
    from app.core.redis import cache_set
    data = {
        "status": task.status,
        "result": task.result.model_dump() if task.result else None,
        "error": task.error,
    }
    await cache_set(f"{_TASK_PREFIX}{task_id}", data, ttl=_TASK_TTL)


async def _load_task(task_id: str) -> Optional[_Task]:
    from app.core.redis import cache_get
    data = await cache_get(f"{_TASK_PREFIX}{task_id}")
    if data is None:
        return None
    task = _Task(status=data["status"], error=data.get("error"))
    if data.get("result"):
        task.result = GeneratedRoute(**data["result"])
    return task


def create_task(form: RouteBuilderForm) -> str:
    task_id = uuid.uuid4().hex
    asyncio.get_event_loop().create_task(_run_generation(task_id, form))
    return task_id


async def get_task(task_id: str) -> Optional[_Task]:
    return await _load_task(task_id)


async def _run_generation(task_id: str, form: RouteBuilderForm):
    task = _Task()
    await _save_task(task_id, task)
    try:
        result = await _generate_route(form)
        task.status = "completed"
        task.result = result
    except HTTPException as e:
        task.status = "failed"
        task.error = e.detail
    except Exception as e:
        logger.error("Task %s failed: %s", task_id, e)
        task.status = "failed"
        task.error = "Internal error"
    await _save_task(task_id, task)


# ---------------------------------------------------------------------------
# Main pipeline: AI → Geocode → Route → GeneratedRoute
# ---------------------------------------------------------------------------

async def _generate_route(form: RouteBuilderForm) -> GeneratedRoute:
    if not settings.YANDEX_GPT_API_KEY:
        raise HTTPException(status_code=503, detail="YandexGPT API key not configured")
    if not settings.YANDEX_GEOCODER_API_KEY:
        raise HTTPException(status_code=503, detail="Yandex Geocoder API key not configured")

    # Step 1: Ask AI for route description + waypoint names
    user_prompt = _build_user_prompt(form)
    ai_data = await _call_llm(user_prompt)

    raw_waypoints = ai_data.get("waypoints", [])
    if len(raw_waypoints) < 2:
        raise HTTPException(status_code=502, detail="AI returned too few waypoints")

    # Determine region for geocoder bias
    region_hint = ai_data.get("region") or form.region

    # Use AI-suggested distance for outlier detection threshold
    expected_distance_km = ai_data.get("distance_km") or (form.distance_km if form.distance_km else None)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 2: Geocode waypoint names → coordinates (biased by region)
        geocoded_waypoints = await _geocode_waypoints(
            client, raw_waypoints, region=region_hint, expected_distance_km=expected_distance_km,
        )

        if len(geocoded_waypoints) < 2:
            raise HTTPException(
                status_code=502,
                detail="Could not geocode enough waypoints",
            )

        # Step 3: Build route geometry via OSRM
        geometry = await _build_route_geometry(client, geocoded_waypoints)

    # Snap waypoints to geometry if we got a route
    if geometry:
        _snap_waypoints_to_geometry(geocoded_waypoints, geometry["coordinates"])

    # Step 4: Fetch real photos from Wikimedia Commons near waypoints
    photos = await _fetch_photos_for_waypoints(geocoded_waypoints)

    # Build final response
    ai_data["waypoints"] = [
        {"lat": wp["lat"], "lng": wp["lng"], "name": wp["name"], "description": wp.get("description")}
        for wp in geocoded_waypoints
    ]
    ai_data["geometry"] = geometry
    ai_data["photos"] = photos

    return GeneratedRoute(**ai_data)


def _snap_waypoints_to_geometry(waypoints: list[dict], coordinates: list[list[float]]):
    """Snap each waypoint to the nearest point on the route geometry."""
    for wp in waypoints:
        best_dist = float("inf")
        best_coord = None
        for coord in coordinates:
            c_lng, c_lat = coord[0], coord[1]
            dist = (c_lat - wp["lat"]) ** 2 + (c_lng - wp["lng"]) ** 2
            if dist < best_dist:
                best_dist = dist
                best_coord = coord
        if best_coord is not None:
            wp["lat"] = best_coord[1]
            wp["lng"] = best_coord[0]


async def _call_llm(user_prompt: str) -> dict:
    """Call YandexGPT and return parsed JSON dict."""
    model = settings.YANDEX_GPT_MODEL
    model_uri = f"gpt://{settings.YANDEX_GPT_FOLDER_ID}/{model}"

    headers = {
        "Authorization": f"Api-Key {settings.YANDEX_GPT_API_KEY}",
        "Content-Type": "application/json",
    }

    if _is_openai_compat(model):
        url = YANDEX_OPENAI_URL
        body = {
            "model": model_uri,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 2000,
            "temperature": 0.6,
        }
    else:
        url = YANDEX_GPT_URL
        body = {
            "modelUri": model_uri,
            "completionOptions": {
                "stream": False,
                "temperature": 0.6,
                "maxTokens": 2000,
            },
            "messages": [
                {"role": "system", "text": SYSTEM_PROMPT},
                {"role": "user", "text": user_prompt},
            ],
        }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error("AI API error: %s %s", e.response.status_code, e.response.text)
            raise HTTPException(status_code=502, detail="AI service returned an error")
        except httpx.RequestError as e:
            logger.error("AI request failed: %s", e)
            raise HTTPException(status_code=502, detail="AI service unavailable")

    result = resp.json()

    if _is_openai_compat(model):
        raw_text = result["choices"][0]["message"]["content"]
    else:
        raw_text = result["result"]["alternatives"][0]["message"]["text"]

    try:
        return _extract_json(raw_text)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error("Failed to parse AI response: %s\nRaw: %s", e, raw_text)
        raise HTTPException(status_code=502, detail="AI returned invalid response format")
