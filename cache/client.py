from __future__ import annotations

import structlog
from redis.asyncio import ConnectionPool, Redis

from config.settings import settings
from utils.notify import notify_admins

log = structlog.get_logger(__name__)

_redis: Redis | None = None


async def init_redis() -> None:
    """Initialize Redis connection pool and client."""
    global _redis
    if _redis is not None:
        return

    log.info("initializing_redis_client", url=settings.redis.url)
    try:
        pool = ConnectionPool.from_url(
            settings.redis.url,
            max_connections=settings.redis.pool_size,
            decode_responses=True,
        )
        _redis = Redis(connection_pool=pool)
        await _redis.ping()
    except Exception as e:
        log.error("redis_connection_failed", error=str(e))
        # Use centralized get_bot to break circular dependency and notify admins
        try:
            from utils.bot import get_bot
            bot = get_bot()
            await notify_admins(bot, f"🚨 <b>Redis Connection Failed!</b>\nError: <code>{str(e)}</code>")
        except Exception as notify_err:
            log.error("failed_to_notify_redis_error", error=str(notify_err))
        raise


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
        log.info("closing_redis_connection_pool")
        await _redis.aclose()
        _redis = None
