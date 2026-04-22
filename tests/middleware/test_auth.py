from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import User as TelegramUser
from aiogram.types import Message

from database.models import User
from middleware.auth import AuthMiddleware


class TestAuthMiddleware:
    """Tests for AuthMiddleware."""

    @pytest.fixture
    def middleware(self):
        return AuthMiddleware()

    @pytest.fixture
    def handler(self):
        return AsyncMock()

    @pytest.fixture
    def telegram_user(self):
        return TelegramUser(id=123, is_bot=False, first_name="Test", username="testuser")

    @pytest.fixture
    def message(self, telegram_user):
        msg = MagicMock(spec=Message)
        msg.from_user = telegram_user
        return msg

    async def test_non_user_event(self, middleware, handler):
        """Test that events without from_user are passed through."""
        event = MagicMock()
        data = {}  # event_from_user is missing
        await middleware(handler, event, data)
        handler.assert_called_once_with(event, data)

    async def test_bot_user_event(self, middleware, handler):
        """Test that events from bots are passed through."""
        event = MagicMock()
        user = TelegramUser(id=123, is_bot=True, first_name="Bot")
        data = {"event_from_user": user}
        await middleware(handler, event, data)
        handler.assert_called_once_with(event, data)

    async def test_new_user_creation(self, middleware, handler, message, mock_db_session):
        """Test that a new user is created in the database."""
        data = {"event_from_user": message.from_user}
        await middleware(handler, message, data)

        handler.assert_called_once()
        assert "db_user" in data
        assert "user_settings" in data
        assert data["db_user"].telegram_id == 123
        assert data["db_user"].username == "testuser"

    async def test_existing_user_update(self, middleware, handler, message, mock_db_session, db_session):
        """Test that an existing user is updated."""
        telegram_id = 456
        message.from_user = message.from_user.model_copy(update={"id": telegram_id})
        
        # Pre-create user
        user = User(telegram_id=telegram_id, username="oldname", first_name="Old")
        db_session.add(user)
        await db_session.commit()

        data = {"event_from_user": message.from_user}
        await middleware(handler, message, data)

        handler.assert_called_once()
        assert data["db_user"].username == "testuser"
        assert data["db_user"].first_name == "Test"

    async def test_banned_user_dropped(self, middleware, handler, message, mock_db_session, db_session):
        """Test that banned users are silently dropped."""
        telegram_id = 999
        message.from_user = message.from_user.model_copy(update={"id": telegram_id})

        # Pre-create banned user
        user = User(telegram_id=telegram_id, username="banneduser", first_name="Banned", is_banned=True)
        db_session.add(user)
        await db_session.commit()

        data = {"event_from_user": message.from_user}
        await middleware(handler, message, data)

        handler.assert_not_called()
        assert "db_user" not in data
