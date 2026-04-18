from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config.settings import settings

# Single engine per process — do not create multiple engines
engine_kwargs: dict[str, Any] = {
    "echo": settings.database.echo,
    "pool_pre_ping": True,
}

if not str(settings.database.url).startswith("sqlite"):
    engine_kwargs["pool_size"] = settings.database.pool_size
    engine_kwargs["max_overflow"] = settings.database.max_overflow

engine = create_async_engine(
    str(settings.database.url),
    **engine_kwargs,
)

AsyncSessionFactory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    # expire_on_commit=False: objects remain usable after commit
    # Without this, accessing any attribute after commit triggers a new DB query
)


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for DB sessions.

    Usage:
        async with get_db() as session:
            user = await crud.get_user_by_telegram_id(session, telegram_id)

    NEVER create sessions manually. ALWAYS use this context manager.
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
