from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import User as TelegramUser

from middleware.logging import LoggingMiddleware


class TestLoggingMiddleware:
    """Tests for LoggingMiddleware."""

    @pytest.fixture
    def middleware(self):
        return LoggingMiddleware()

    @pytest.fixture
    def handler(self):
        return AsyncMock()

    @pytest.fixture
    def telegram_user(self):
        return TelegramUser(id=123, is_bot=False, first_name="Test", username="testuser")

    @patch("structlog.contextvars.bind_contextvars")
    @patch("structlog.contextvars.clear_contextvars")
    async def test_logging_context_binding(
        self, mock_clear, mock_bind, middleware, handler, telegram_user
    ):
        """Test that user context is bound and cleared."""
        event = MagicMock()
        event.from_user = telegram_user
        event.update_id = 456
        data = {}

        await middleware(handler, event, data)

        mock_bind.assert_called_once_with(
            user_id=123,
            username="testuser",
            update_id=456,
        )
        handler.assert_called_once_with(event, data)
        mock_clear.assert_called_once()

    @patch("structlog.contextvars.bind_contextvars")
    @patch("structlog.contextvars.clear_contextvars")
    async def test_logging_context_cleared_on_error(
        self, mock_clear, mock_bind, middleware, handler, telegram_user
    ):
        """Test that context is cleared even if handler raises an exception."""
        event = MagicMock()
        event.from_user = telegram_user
        data = {}
        handler.side_effect = ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            await middleware(handler, event, data)

        mock_clear.assert_called_once()

    @patch("structlog.contextvars.bind_contextvars")
    @patch("structlog.contextvars.clear_contextvars")
    async def test_logging_no_user(
        self, mock_clear, mock_bind, middleware, handler
    ):
        """Test logging when there is no user in the event."""
        event = MagicMock()
        event.from_user = None
        event.update_id = 789
        data = {}

        await middleware(handler, event, data)

        mock_bind.assert_called_once_with(
            user_id=None,
            username=None,
            update_id=789,
        )
        mock_clear.assert_called_once()
