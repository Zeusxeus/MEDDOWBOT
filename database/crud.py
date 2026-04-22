from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Optional, Sequence

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import (
    CookieFile,
    DownloadJob,
    JobStatus,
    Proxy,
    RateLimitLog,
    User,
    UserSettings,
)


# ─────────────────────────────────────────────
# USER
# ─────────────────────────────────────────────


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> Optional[User]:
    """Fetch user by Telegram ID with settings loaded."""
    stmt = select(User).where(User.telegram_id == telegram_id).options(selectinload(User.settings))
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def upsert_user(
    session: AsyncSession,
    telegram_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
) -> User:
    """Create or update user on interaction."""
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_seen_at=datetime.now(UTC),
        )
        session.add(user)
        await session.flush()
        # Create default settings
        settings = UserSettings(user_id=user.id)
        session.add(settings)
        await session.flush()
        # Re-fetch to ensure settings are loaded
        user = await get_user_by_telegram_id(session, telegram_id)
        if not user:
            raise RuntimeError("Failed to create user")
    else:
        user.username = username
        user.first_name = first_name
        user.last_seen_at = datetime.now(UTC)
    return user


async def set_user_ban(session: AsyncSession, telegram_id: int, is_banned: bool) -> bool:
    """Ban or unban user."""
    stmt = update(User).where(User.telegram_id == telegram_id).values(is_banned=is_banned)
    result = await session.execute(stmt)
    return result.rowcount > 0


# ─────────────────────────────────────────────
# USER SETTINGS
# ─────────────────────────────────────────────


async def update_user_settings(session: AsyncSession, user_id: uuid.UUID, **kwargs) -> None:
    """Update user preferences."""
    stmt = update(UserSettings).where(UserSettings.user_id == user_id).values(**kwargs)
    await session.execute(stmt)


# ─────────────────────────────────────────────
# DOWNLOAD JOB
# ─────────────────────────────────────────────


async def create_download_job(
    session: AsyncSession,
    user_id: uuid.UUID,
    url: str,
    format_requested: str,
    job_id: Optional[uuid.UUID] = None,
) -> DownloadJob:
    """Create a new download record."""
    job = DownloadJob(
        id=job_id or uuid.uuid4(),
        user_id=user_id,
        url=url,
        format_requested=format_requested,
    )
    session.add(job)
    await session.flush()
    return job


async def update_job_status(
    session: AsyncSession,
    job_id: uuid.UUID,
    status: JobStatus,
    error_message: Optional[str] = None,
    error_type: Optional[str] = None,
    **kwargs,
) -> None:
    """Update job state and optional error info."""
    values = {"status": status, **kwargs}
    if error_message:
        values["error_message"] = error_message
    if error_type:
        values["error_type"] = error_type
    if status == JobStatus.RUNNING:
        values["started_at"] = datetime.now(UTC)
    elif status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED):
        values["completed_at"] = datetime.now(UTC)

    stmt = update(DownloadJob).where(DownloadJob.id == job_id).values(**values)
    await session.execute(stmt)


async def cancel_job(session: AsyncSession, job_id: uuid.UUID) -> bool:
    """
    Cancel an active job. Returns True if successfully cancelled.
    Only PENDING or RUNNING jobs can be cancelled.
    """
    stmt = (
        update(DownloadJob)
        .where(
            DownloadJob.id == job_id,
            DownloadJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
        )
        .values(
            status=JobStatus.CANCELLED,
            completed_at=datetime.now(UTC),
        )
    )
    result = await session.execute(stmt)
    return result.rowcount > 0


async def get_active_job_by_user(session: AsyncSession, user_id: uuid.UUID) -> Optional[DownloadJob]:
    """Get the most recent active job for a user."""
    stmt = (
        select(DownloadJob)
        .where(
            DownloadJob.user_id == user_id,
            DownloadJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
        )
        .order_by(DownloadJob.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_history(
    session: AsyncSession, user_id: uuid.UUID, limit: int = 10, offset: int = 0
) -> Sequence[DownloadJob]:
    """Get paginated job history for a user."""
    stmt = (
        select(DownloadJob)
        .where(DownloadJob.user_id == user_id)
        .order_by(DownloadJob.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def count_user_history(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Count total jobs for a user."""
    from sqlalchemy import func

    stmt = select(func.count()).select_from(DownloadJob).where(DownloadJob.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar() or 0


async def clear_user_history(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Delete all job history for a user."""
    stmt = delete(DownloadJob).where(DownloadJob.user_id == user_id)
    await session.execute(stmt)


# ─────────────────────────────────────────────
# PROXY
# ─────────────────────────────────────────────


async def add_proxy(session: AsyncSession, proxy: Proxy) -> Proxy:
    """Add a new proxy to the pool."""
    session.add(proxy)
    await session.flush()
    return proxy


async def get_all_proxies(session: AsyncSession) -> Sequence[Proxy]:
    """List all proxies for admin."""
    stmt = select(Proxy).order_by(Proxy.added_at.desc())
    result = await session.execute(stmt)
    return result.scalars().all()


async def delete_proxy(session: AsyncSession, proxy_id: uuid.UUID) -> bool:
    """Remove a proxy from the pool."""
    stmt = delete(Proxy).where(Proxy.id == proxy_id)
    result = await session.execute(stmt)
    return result.rowcount > 0


# ─────────────────────────────────────────────
# COOKIE FILE
# ─────────────────────────────────────────────


async def get_active_cookie(session: AsyncSession, platform: str) -> Optional[CookieFile]:
    """Get the active cookie file for a platform."""
    stmt = select(CookieFile).where(CookieFile.platform == platform, CookieFile.is_active)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def deactivate_all_cookies(session: AsyncSession, platform: str) -> None:
    """Deactivate all cookies for a platform before adding a new one."""
    stmt = update(CookieFile).where(CookieFile.platform == platform).values(is_active=False)
    await session.execute(stmt)


# ─────────────────────────────────────────────
# ANALYTICS
# ─────────────────────────────────────────────


async def log_rate_limit(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Record a rate limit event."""
    log = RateLimitLog(user_id=user_id)
    session.add(log)


async def increment_user_stats(session: AsyncSession, user_id: uuid.UUID, bytes_served: int) -> None:
    """Increment denormalized user counters."""
    stmt = (
        update(User)
        .where(User.id == user_id)
        .values(
            total_downloads=User.total_downloads + 1,
            total_bytes_served=User.total_bytes_served + bytes_served,
        )
    )
    await session.execute(stmt)
