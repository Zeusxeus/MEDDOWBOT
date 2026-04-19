from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Message, User as TelegramUser

from database.models import User, RateLimitLog
from middleware.rate_limit import RateLimitMiddleware
from sqlalchemy import select


class TestRateLimitMiddleware:
    """Tests for RateLimitMiddleware."""

    @pytest.fixture
    def middleware(self):
        return RateLimitMiddleware()

    @pytest.fixture
    def handler(self):
        return AsyncMock()

    @pytest.fixture
    def telegram_user(self):
        return TelegramUser(id=123, is_bot=False, first_name="Test")

    @pytest.fixture
    def message(self, telegram_user):
        msg = MagicMock(spec=Message)
        msg.from_user = telegram_user
        msg.text = "/download https://example.com"
        msg.answer = AsyncMock()
        return msg

    @pytest.fixture
    async def db_user(self, db_session):
        user = User(telegram_id=123, is_admin=False)
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        return user

    async def test_non_message_event(self, middleware, handler):
        """Test that non-message events are passed through."""
        event = MagicMock()
        data = {}
        await middleware(handler, event, data)
        handler.assert_called_once_with(event, data)

    async def test_no_db_user(self, middleware, handler, message):
        """Test that events without db_user in data are passed through."""
        data = {}
        await middleware(handler, message, data)
        handler.assert_called_once_with(message, data)

    async def test_admin_bypass(self, middleware, handler, message, db_user):
        """Test that admins bypass rate limiting."""
        db_user.is_admin = True
        data = {"db_user": db_user}
        await middleware(handler, message, data)
        handler.assert_called_once_with(message, data)

    @patch("middleware.rate_limit.check_rate_limit")
    async def test_under_limit_allowed(self, mock_check, middleware, handler, message, db_user):
        """Test that users under limit are allowed."""
        mock_check.return_value = (True, 0)
        data = {"db_user": db_user}
        await middleware(handler, message, data)
        handler.assert_called_once_with(message, data)
        message.answer.assert_not_called()

    @patch("middleware.rate_limit.check_rate_limit")
    async def test_over_limit_blocked(self, mock_check, middleware, handler, message, db_user, mock_db_session, db_session):
        """Test that users over limit are blocked and logged."""
        mock_check.return_value = (False, 60)
        data = {"db_user": db_user}
        
        await middleware(handler, message, data)
        
        handler.assert_not_called()
        message.answer.assert_called_once_with("⚠️ Rate limit exceeded. Try again in 60 seconds.")
        
        # Check if logged to DB
        stmt = select(RateLimitLog).where(RateLimitLog.user_id == db_user.id)
        result = await db_session.execute(stmt)
        logs = result.scalars().all()
        assert len(logs) == 1

    @patch("middleware.rate_limit.check_rate_limit")
    async def test_non_download_command_allowed(self, mock_check, middleware, handler, message, db_user):
        """Test that non-download commands/messages don't trigger rate limit."""
        message.text = "Just a message"
        data = {"db_user": db_user}
        await middleware(handler, message, data)
        handler.assert_called_once_with(message, data)
        mock_check.assert_not_called()

    @patch("middleware.rate_limit.check_rate_limit")
    async def test_url_message_triggers_limit(self, mock_check, middleware, handler, message, db_user):
        """Test that plain URL messages also trigger rate limit."""
        message.text = "https://youtube.com/watch?v=123"
        mock_check.return_value = (True, 0)
        data = {"db_user": db_user}
        await middleware(handler, message, data)
        handler.assert_called_once_with(message, data)
        mock_check.assert_called_once()
