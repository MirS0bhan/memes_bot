"""Redis client (spec §7.1) for rate limiting, inline caches, and removal-review tallies."""

import redis.asyncio as aioredis

from app.config import get_settings

settings = get_settings()

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    if _redis is not None:
        await _redis.aclose()


async def rate_limit(key: str, limit: int, window: int) -> bool:
    """Fixed-window counter rate limit. Returns True if the request is allowed."""
    r = await get_redis()
    pipe = r.pipeline()
    await pipe.incr(key)
    await pipe.expire(key, window, nx=True)
    results = await pipe.execute()
    return results[0] <= limit
