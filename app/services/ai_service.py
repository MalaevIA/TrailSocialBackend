import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Optional

import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.schemas.ai import RouteBuilderForm, GeneratedRoute

logger = logging.getLogger(__name__)

YANDEX_GPT_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
YANDEX_OPENAI_URL = "https://llm.api.cloud.yandex.net/v1/chat/completions"
YANDEX_GEOCODER_URL = "https://geocode-maps.yandex.ru/1.x/"
OSRM_ROUTE_URL = "https://router.project-osrm.org/route/v1/foot"

# Models that require OpenAI-compatible API instead of gRPC
OPENAI_COMPAT_MODELS = {"qwen3-235b-a22b-fp8", "deepseek-v32", "gemma-3-27b-it", "gpt-oss-120b", "gpt-oss-20b"}

SYSTEM_PROMPT = """Ты — помощник для приложения Trail Social. Твоя задача — предложить маршрут для прогулки/похода на основе предпочтений пользователя.

## Важно

Ты НЕ генерируешь координаты. Координаты будут получены автоматически через геокодер.
Вместо координат ты указываешь **названия реальных мест** (улицы, парки, достопримечательности, точки на тропе).

## Правила

1. Предлагай реально существующие места в указанном регионе.
2. Waypoints — это ключевые точки маршрута (начало, интересные места, конец). Минимум 3, максимум 8.
3. Каждый waypoint должен иметь уникальное, конкретное название, по которому геокодер найдёт это место.
   - Хорошо: "Красная площадь, Москва", "Парк Зарядье, Москва"
   - Плохо: "Начало маршрута", "Интересная точка"
4. Указывай город/регион в названии waypoint для точности геокодинга.
5. Набор высоты должен соответствовать сложности и рельефу региона.
6. Длительность и дистанция должны быть согласованы:
   - easy: 3–4 км/ч
   - moderate: 2.5–3.5 км/ч
   - hard: 2–3 км/ч
   - expert: 1.5–2.5 км/ч
7. Весь текст — на русском языке.

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
    {"name": "string — точное название места с городом/регионом", "description": "string или null"}
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

async def _geocode(client: httpx.AsyncClient, place_name: str) -> Optional[tuple[float, float]]:
    """Geocode a place name → (lat, lng) using Yandex Geocoder."""
    try:
        resp = await client.get(YANDEX_GEOCODER_URL, params={
            "apikey": settings.YANDEX_GEOCODER_API_KEY,
            "geocode": place_name,
            "format": "json",
            "results": 1,
        })
        resp.raise_for_status()
        data = resp.json()
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
) -> list[dict]:
    """Geocode all waypoints in parallel, skip those that fail."""
    tasks = [_geocode(client, wp["name"]) for wp in waypoints]
    results = await asyncio.gather(*tasks)

    geocoded = []
    for wp, coords in zip(waypoints, results):
        if coords is not None:
            lat, lng = coords
            geocoded.append({**wp, "lat": lat, "lng": lng})
        else:
            logger.warning("Skipping waypoint '%s' — geocoding failed", wp["name"])
    return geocoded


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
        resp = await client.get(url, params={
            "overview": "full",
            "geometries": "geojson",
        })
        resp.raise_for_status()
        data = resp.json()

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
# Task management (in-memory)
# ---------------------------------------------------------------------------

@dataclass
class _Task:
    status: str = "pending"  # pending | completed | failed
    result: Optional[GeneratedRoute] = None
    error: Optional[str] = None

_tasks: dict[str, _Task] = {}

MAX_TASKS = 1000


def _cleanup_tasks():
    if len(_tasks) > MAX_TASKS:
        to_remove = list(_tasks.keys())[:len(_tasks) - MAX_TASKS]
        for k in to_remove:
            del _tasks[k]


def create_task(form: RouteBuilderForm) -> str:
    _cleanup_tasks()
    task_id = uuid.uuid4().hex
    _tasks[task_id] = _Task()
    asyncio.get_event_loop().create_task(_run_generation(task_id, form))
    return task_id


def get_task(task_id: str) -> Optional[_Task]:
    return _tasks.get(task_id)


async def _run_generation(task_id: str, form: RouteBuilderForm):
    task = _tasks[task_id]
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

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 2: Geocode waypoint names → coordinates
        geocoded_waypoints = await _geocode_waypoints(client, raw_waypoints)

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

    # Build final response
    ai_data["waypoints"] = [
        {"lat": wp["lat"], "lng": wp["lng"], "name": wp["name"], "description": wp.get("description")}
        for wp in geocoded_waypoints
    ]
    ai_data["geometry"] = geometry

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
