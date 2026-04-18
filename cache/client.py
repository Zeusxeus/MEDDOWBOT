from __future__ import annotations

import structlog
from redis.asyncio import ConnectionPool, Redis

from config.settings import settings

log = structlog.get_logger(__name__)

_redis: Redis | None = None


async def init_redis() -> None:
    """Initialize Redis connection pool and client."""
    global _redis
    if _redis is not None:
        return

    log.info("Initializing Redis client", url=settings.redis.url)
    pool = ConnectionPool.from_url(
        settings.redis.url,
        max_connections=settings.redis.pool_size,
        decode_responses=True,
    )
    _redis = Redis(connection_pool=pool)


def get_redis() -> Redis:
    """
    Get the Redis singleton instance.

    Raises:
        RuntimeError: If Redis has not been initialized.
    """
    if _redis is None:
        raise RuntimeError("Redis is not initialized. Call init_redis() first.")
    return _redis


async def close_redis() -> None:
    """Close Redis connection pool."""
    global _redis
    if _redis:
        log.info("Closing Redis connection pool")
        await _redis.aclose()
        _redis = None
