from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from config.settings import settings
from database.models import Proxy, ProxyStatus
from utils.proxy import proxy_pool


def ensure_aware(dt: datetime | None) -> datetime | None:
    """Ensure datetime is timezone-aware."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class TestProxyModel:
    """Tests for the Proxy model logic."""

    def test_from_string_valid(self):
        """Test parsing a valid proxy string."""
        proxy_str = "45.56.180.147:8381:jhrwjggg:axrxuy5m3k18"
        proxy = Proxy.from_string(proxy_str)
        
        assert proxy.host == "45.56.180.147"
        assert proxy.port == 8381
        assert proxy.username == "jhrwjggg"
        assert proxy.password == "axrxuy5m3k18"

    def test_from_string_invalid(self):
        """Test parsing invalid proxy strings."""
        invalid_strings = [
            "invalid_format",
            "host:port:user",  # Missing password
            "host:not_a_port:user:pass",
            "host:70000:user:pass",  # Port out of range
        ]
        for s in invalid_strings:
            with pytest.raises(ValueError):
                Proxy.from_string(s)

    def test_ytdlp_url_format(self):
        """Verify Proxy.ytdlp_url format."""
        proxy = Proxy(
            host="localhost",
            port=8080,
            username="user",
            password="pass"
        )
        assert proxy.ytdlp_url == "http://user:pass@localhost:8080"

    def test_display_str_hides_password(self):
        """Verify Proxy.display_str hides the password."""
        proxy = Proxy(
            host="localhost",
            port=8080,
            username="user",
            password="pass"
        )
        display = proxy.display_str
        assert "pass" not in display
        assert "***" in display
        assert "localhost" in display
        assert "8080" in display
        assert "user" in display


class TestProxyPool:
    """Tests for the ProxyPool logic."""

    @pytest.mark.asyncio
    async def test_pool_disabled_returns_none(self, monkeypatch):
        """If proxy is disabled in settings, return None."""
        monkeypatch.setattr(settings.proxy, "enabled", False)
        
        result = await proxy_pool.get_proxy_for_url("https://youtube.com/watch?v=abc")
        assert result is None

    @pytest.mark.asyncio
    async def test_round_robin_picks_oldest(self, mock_db_session, monkeypatch):
        """Verify round_robin strategy picks the proxy with the oldest last_used_at."""
        monkeypatch.setattr(settings.proxy, "enabled", True)
        monkeypatch.setattr(settings.proxy, "rotation_strategy", "round_robin")
        
        db_session = mock_db_session
        now = datetime.now(timezone.utc)
        
        # Create two proxies
        p1 = Proxy(
            host="proxy1", port=8080, username="u1", password="p1",
            status=ProxyStatus.ACTIVE,
            last_used_at=now - timedelta(minutes=10)
        )
        p2 = Proxy(
            host="proxy2", port=8080, username="u2", password="p2",
            status=ProxyStatus.ACTIVE,
            last_used_at=now - timedelta(minutes=5)
        )
        db_session.add_all([p1, p2])
        await db_session.commit()
        
        # Should pick p1 (older)
        selected = await proxy_pool.get_proxy_for_url("https://youtube.com/watch?v=abc")
        assert selected is not None
        assert selected.host == "proxy1"
        
        # Refresh p1 from DB to check if last_used_at was updated
        await db_session.refresh(p1)
        last_used = ensure_aware(p1.last_used_at)
        assert last_used > now - timedelta(seconds=5)
        assert p1.total_uses == 1

        # Next call should pick p2
        selected2 = await proxy_pool.get_proxy_for_url("https://youtube.com/watch?v=abc")
        assert selected2 is not None
        assert selected2.host == "proxy2"

    @pytest.mark.asyncio
    async def test_no_proxy_platforms(self, monkeypatch):
        """Verify proxies are skipped for excluded platforms."""
        monkeypatch.setattr(settings.proxy, "enabled", True)
        monkeypatch.setattr(settings.proxy, "no_proxy_platforms", ["google.com"])
        
        result = await proxy_pool.get_proxy_for_url("https://google.com/search")
        assert result is None
