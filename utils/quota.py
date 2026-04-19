from __future__ import annotations

import shutil

import structlog

from cache.client import get_redis
from config.settings import settings

log = structlog.get_logger(__name__)


class DiskSpaceError(Exception):
    """Raised when there is not enough disk space."""


class QuotaError(Exception):
    """Raised when a user quota is exceeded."""


async def check_disk_space() -> None:
    """
    Raises DiskSpaceError if free space < settings.disk.min_free_gb.

    Raises:
        DiskSpaceError: If free disk space is below the configured threshold.
    """
    # Use the parent of downloads_path to check the mount point
    path = settings.disk.downloads_path
    path.mkdir(parents=True, exist_ok=True)

    _, _, free = shutil.disk_usage(path)
    free_gb = free / (1024**3)

    if free_gb < settings.disk.min_free_gb:
        log.error("low_disk_space", free_gb=free_gb, limit=settings.disk.min_free_gb)
        raise DiskSpaceError(
            f"Not enough disk space: {free_gb:.2f}GB free, "
            f"minimum required {settings.disk.min_free_gb}GB"
        )


async def check_and_increment_concurrent(user_id_str: str) -> None:
    """
    Uses Redis key concurrent:{user_id} to limit jobs to settings.rate_limit.max_concurrent_jobs.

    Args:
        user_id_str: The Telegram user ID as a string.

    Raises:
        QuotaError: If the maximum number of concurrent jobs is reached.
    """
    redis = get_redis()
    key = f"concurrent:{user_id_str}"

    # Atomic increment
    current = await redis.incr(key)

    if current > settings.rate_limit.max_concurrent_jobs:
        # Revert increment if limit exceeded
        await redis.decr(key)
        log.warning(
            "max_concurrent_jobs_reached",
            user_id=user_id_str,
            limit=settings.rate_limit.max_concurrent_jobs,
        )
        raise QuotaError(
            f"Maximum concurrent jobs ({settings.rate_limit.max_concurrent_jobs}) reached"
        )


async def decrement_concurrent(user_id_str: str) -> None:
    """
    Decrements the Redis counter for concurrent jobs.

    Args:
        user_id_str: The Telegram user ID as a string.
    """
    redis = get_redis()
    key = f"concurrent:{user_id_str}"

    current = await redis.get(key)
    if current and int(current) > 0:
        await redis.decr(key)
    else:
        # Ensure it stays at 0 if it was already 0 or None
        await redis.set(key, 0)
