from __future__ import annotations

from typing import Any, cast

import structlog

from cache.client import get_redis
from config.settings import settings

log = structlog.get_logger(__name__)

# Lua script for atomic rate limiting
# KEYS[1]: rate limit key
# ARGV[1]: window in seconds
# ARGV[2]: limit (max requests)
# Returns: {allowed (0 or 1), ttl}
RATE_LIMIT_LUA = """
local current = redis.call("INCR", KEYS[1])
if current == 1 then
    redis.call("EXPIRE", KEYS[1], ARGV[1])
end
local ttl = redis.call("TTL", KEYS[1])
if current > tonumber(ARGV[2]) then
    return {0, ttl}
end
return {1, ttl}
"""


async def check_rate_limit(user_id: int, override_limit: int | None = None) -> tuple[bool, int]:
    """
    Check if a user has exceeded their rate limit.

    Args:
        user_id: The Telegram user ID.
        override_limit: Optional limit override (requests per hour).

    Returns:
        A tuple of (allowed: bool, reset_in: int).
    """
    redis = get_redis()
    key = f"{settings.redis.cache_prefix}:ratelimit:{user_id}"

    # We use 1 hour window
    window = 3600
    
    if override_limit is not None:
        limit = override_limit
    else:
        limit = settings.rate_limit.requests_per_minute * 60

    try:
        # result format: [allowed, ttl]
        # We cast to Any to satisfy mypy's confusion over redis-py's return types
        raw_result = await cast(Any, redis.eval(RATE_LIMIT_LUA, 1, key, str(window), str(limit)))
        result = cast(list[int], raw_result)
        allowed = bool(result[0])
        reset_in = result[1]

        if not allowed:
            log.warning("Rate limit exceeded", user_id=user_id, reset_in=reset_in, limit=limit)

        return allowed, reset_in
    except Exception as e:
        log.error("Rate limit check failed", user_id=user_id, error=str(e))
        # Fail open to avoid blocking users on Redis issues
        return True, 0
