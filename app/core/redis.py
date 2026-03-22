import json
import logging
from typing import Any, Optional

from redis.asyncio import Redis, ConnectionPool

from app.core.config import settings

logger = logging.getLogger(__name__)

_pool: Optional[ConnectionPool] = None


def get_redis_pool() -> Optional[ConnectionPool]:
    global _pool
    if not settings.REDIS_URL:
        return None
    if _pool is None:
        _pool = ConnectionPool.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=20,
        )
    return _pool


def get_redis() -> Optional[Redis]:
    pool = get_redis_pool()
    return Redis(connection_pool=pool) if pool else None


async def cache_get(key: str) -> Optional[Any]:
    r = get_redis()
    if r is None:
        return None
    try:
        async with r as client:
            value = await client.get(key)
            return json.loads(value) if value else None
    except Exception as e:
        logger.warning("Redis cache_get failed for key '%s': %s", key, e)
        return None


async def cache_set(key: str, value: Any, ttl: int = settings.CACHE_TTL_SECONDS) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        async with r as client:
            await client.set(key, json.dumps(value, default=str), ex=ttl)
    except Exception as e:
        logger.warning("Redis cache_set failed for key '%s': %s", key, e)


async def cache_delete(key: str) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        async with r as client:
            await client.delete(key)
    except Exception as e:
        logger.warning("Redis cache_delete failed for key '%s': %s", key, e)


async def cache_delete_pattern(pattern: str) -> None:
    """Удалить все ключи по паттерну, например 'recommended:*'"""
    r = get_redis()
    if r is None:
        return
    try:
        async with r as client:
            keys = await client.keys(pattern)
            if keys:
                await client.delete(*keys)
    except Exception as e:
        logger.warning("Redis cache_delete_pattern failed for '%s': %s", pattern, e)
