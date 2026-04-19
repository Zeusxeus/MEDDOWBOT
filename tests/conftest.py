from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database.models import Base


@pytest.fixture
async def test_engine():
    """Create a test database engine."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
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
            pass

    monkeypatch.setattr("database.session.get_db", lambda: AsyncContextManagerMock(db_session))
    monkeypatch.setattr("utils.proxy.get_db", lambda: AsyncContextManagerMock(db_session))
    monkeypatch.setattr("utils.cookies.get_db", lambda: AsyncContextManagerMock(db_session))
    return db_session
