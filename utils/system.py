from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

import structlog
from sqlalchemy import text

from cache.client import get_redis
from database.session import get_db

log = structlog.get_logger(__name__)

# Track bot startup time
BOT_START_TIME = datetime.now(UTC)


@dataclass
class SystemMetrics:
    """System health metrics."""
    uptime: str
    redis_connected: bool
    redis_usage: str
    db_connected: bool
    db_usage: str
    disk_total: str
    disk_used: str
    disk_free: str
    disk_percent: float
    workers_active: int
    queue_depth: int


def format_size(size_bytes: int) -> str:
    """Format bytes to human-readable string."""
    if size_bytes == 0:
        return "0B"
    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}PB"


def get_uptime_str() -> str:
    """Return human-readable uptime."""
    delta = datetime.now(UTC) - BOT_START_TIME
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")

    return " ".join(parts) or "< 1m"


async def get_system_metrics() -> SystemMetrics:
    """Gather all system metrics."""
    # Redis
    redis_connected = False
    redis_usage = "N/A"
    queue_depth = 0
    try:
        redis = get_redis()
        info = await redis.info()
        redis_usage = format_size(int(info["used_memory"]))
        queue_depth = await redis.llen("taskiq")  # type: ignore[misc]
        redis_connected = True
    except Exception:
        log.warning("system_metrics_redis_error")

    # DB
    db_connected = False
    db_usage = "N/A"
    try:
        async with get_db() as session:
            res = await session.execute(text("SELECT pg_database_size(current_database())"))  # type: ignore[misc]
            size = res.scalar() or 0
            db_usage = format_size(cast(int, size))
            db_connected = True
    except Exception:
        log.warning("system_metrics_db_error")

    # Disk
    total, used, free = shutil.disk_usage("/")
    disk_percent = (used / total) * 100

    # Workers
    workers_active = 0
    try:
        from sqlalchemy import func, select
        from database.models import DownloadJob, JobStatus
        async with get_db() as session:
            stmt = select(func.count(DownloadJob.id)).where(DownloadJob.status == JobStatus.RUNNING)
            res_exec = await session.execute(stmt)  # type: ignore[misc]
            workers_active = cast(int, res_exec.scalar() or 0)
    except Exception:
        pass

    return SystemMetrics(
        uptime=get_uptime_str(),
        redis_connected=redis_connected,
        redis_usage=redis_usage,
        db_connected=db_connected,
        db_usage=db_usage,
        disk_total=format_size(total),
        disk_used=format_size(used),
        disk_free=format_size(free),
        disk_percent=round(disk_percent, 1),
        workers_active=workers_active,
        queue_depth=queue_depth,
    )
