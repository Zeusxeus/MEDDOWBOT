from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from aiogram.types import Message

from middleware.ssrf import SSRFProtectionMiddleware


class TestSSRFMiddleware:
    """Tests for SSRFProtectionMiddleware."""

    @pytest.fixture
    def middleware(self):
        return SSRFProtectionMiddleware()

    @pytest.fixture
    def handler(self):
        return AsyncMock()

    @pytest.fixture
    def message(self):
        msg = AsyncMock(spec=Message)
        msg.text = None
        msg.answer = AsyncMock()
        return msg

    async def test_non_message_event(self, middleware, handler):
        """Test that non-message events are passed through."""
        event = AsyncMock()
        data = {}
        await middleware(handler, event, data)
        handler.assert_called_once_with(event, data)

    async def test_message_no_text(self, middleware, handler, message):
        """Test that messages without text are passed through."""
        message.text = None
        data = {}
        await middleware(handler, message, data)
        handler.assert_called_once_with(message, data)

    async def test_non_url_text(self, middleware, handler, message):
        """Test that non-URL text is passed through."""
        message.text = "Hello world"
        data = {}
        await middleware(handler, message, data)
        handler.assert_called_once_with(message, data)

    @patch("middleware.ssrf.socket.getaddrinfo")
    async def test_blocked_ip(self, mock_getaddrinfo, middleware, handler, message):
        """Test that 127.0.0.1 is blocked."""
        message.text = "http://127.0.0.1"
        mock_getaddrinfo.return_value = [(None, None, None, None, ("127.0.0.1", 80))]
        data = {}
        
        await middleware(handler, message, data)
        
        message.answer.assert_called_once_with("❌ Forbidden URL: Private network access is not allowed.")
        handler.assert_not_called()

    @patch("middleware.ssrf.socket.getaddrinfo")
    async def test_allowed_ip(self, mock_getaddrinfo, middleware, handler, message):
        """Test that 8.8.8.8 is allowed."""
        message.text = "https://8.8.8.8"
        mock_getaddrinfo.return_value = [(None, None, None, None, ("8.8.8.8", 443))]
        data = {}
        
        await middleware(handler, message, data)
        
        handler.assert_called_once_with(message, data)
        message.answer.assert_not_called()

    @patch("middleware.ssrf.socket.getaddrinfo")
    async def test_localhost_blocked(self, mock_getaddrinfo, middleware, handler, message):
        """Test that localhost is blocked."""
        message.text = "http://localhost"
        mock_getaddrinfo.return_value = [(None, None, None, None, ("127.0.0.1", 80))]
        data = {}
        
        await middleware(handler, message, data)
        
        message.answer.assert_called_once_with("❌ Forbidden URL: Private network access is not allowed.")
        handler.assert_not_called()

    @patch("middleware.ssrf.socket.getaddrinfo")
    async def test_hostname_resolves_to_private_and_public(self, mock_getaddrinfo, middleware, handler, message):
        """Test that if hostname resolves to at least one private IP, it is blocked."""
        message.text = "http://malicious.com"
        mock_getaddrinfo.return_value = [
            (None, None, None, None, ("1.1.1.1", 80)),
            (None, None, None, None, ("192.168.1.1", 80)),
        ]
        data = {}
        
        await middleware(handler, message, data)
        
        message.answer.assert_called_once_with("❌ Forbidden URL: Private network access is not allowed.")
        handler.assert_not_called()

    @patch("middleware.ssrf.socket.getaddrinfo")
    async def test_dns_failure(self, mock_getaddrinfo, middleware, handler, message):
        """Test that DNS failure doesn't block (fails open or handled)."""
        message.text = "http://nonexistent.domain"
        mock_getaddrinfo.side_effect = Exception("DNS lookup failed")
        data = {}
        
        await middleware(handler, message, data)
        
        handler.assert_called_once_with(message, data)
        message.answer.assert_not_called()
