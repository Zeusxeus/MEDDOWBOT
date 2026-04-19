from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
import fakeredis.aioredis

from database.models import Base


@pytest.fixture
async def test_engine():
    """Create a test database engine."""
    # Use StaticPool to ensure all connections use the same in-memory DB
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


@pytest.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a clean DB session for each test."""
    async_session = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session


@pytest.fixture
async def mock_db_session(db_session, monkeypatch):
    """Mock get_db to return the test db_session."""

    class AsyncContextManagerMock:
        def __init__(self, session):
            self.session = session

        async def __aenter__(self):
            return self.session

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            if exc_type is None:
                await self.session.commit()
            else:
                await self.session.rollback()

    monkeypatch.setattr("database.session.get_db", lambda: AsyncContextManagerMock(db_session))
    monkeypatch.setattr("middleware.auth.get_db", lambda: AsyncContextManagerMock(db_session))
    monkeypatch.setattr("middleware.rate_limit.get_db", lambda: AsyncContextManagerMock(db_session))
    monkeypatch.setattr("utils.proxy.get_db", lambda: AsyncContextManagerMock(db_session))
    monkeypatch.setattr("utils.cookies.get_db", lambda: AsyncContextManagerMock(db_session))
    return db_session


@pytest.fixture
def redis_client():
    """Fake Redis client."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return client


@pytest.fixture(autouse=True)
def mock_get_redis(redis_client, monkeypatch):
    """Monkeypatch get_redis to return the fake client."""
    monkeypatch.setattr("cache.client.get_redis", lambda: redis_client)
    return redis_client
