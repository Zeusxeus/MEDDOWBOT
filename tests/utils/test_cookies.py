from __future__ import annotations

import datetime
import uuid
import pytest

from config.settings import settings
from database.models import CookieFile
from utils.cookies import cookie_manager


class TestCookieManager:
    """Tests for CookieManager."""

    def test_validate_netscape_valid(self):
        """Valid 7-column Netscape string passes."""
        valid_content = (
            "# Netscape HTTP Cookie File\n"
            ".youtube.com\tTRUE\t/\tTRUE\t1741544040\tname\tvalue\n"
        )
        is_valid, error = cookie_manager._validate_netscape_format(valid_content)
        assert is_valid is True
        assert error is None

    def test_validate_netscape_invalid(self):
        """JSON string and 3-column string fail."""
        # JSON string
        json_content = '{"cookie": "value"}'
        is_valid, error = cookie_manager._validate_netscape_format(json_content)
        assert is_valid is False
        assert "expected 7" in error

        # 3-column string
        short_content = "domain\tname\tvalue"
        is_valid, error = cookie_manager._validate_netscape_format(short_content)
        assert is_valid is False
        assert "expected 7" in error

    def test_extract_earliest_expiry(self):
        """Verify it finds the minimum Unix timestamp from the 5th column."""
        future_ts_1 = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=10)).timestamp())
        future_ts_2 = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=20)).timestamp())
        
        content = (
            f"domain1\tTRUE\t/\tTRUE\t{future_ts_2}\tname1\tvalue1\n"
            f"domain2\tTRUE\t/\tTRUE\t{future_ts_1}\tname2\tvalue2\n"
        )
        
        expiry = cookie_manager._extract_earliest_expiry(content)
        assert expiry is not None
        assert int(expiry.timestamp()) == future_ts_1

    @pytest.mark.asyncio
    async def test_get_cookie_file_disabled(self, monkeypatch):
        """Mock settings.cookies.enabled = False and verify get_cookie_file returns None."""
        monkeypatch.setattr(settings.cookies, "enabled", False)
        
        result = await cookie_manager.get_cookie_file("https://youtube.com/watch?v=abc")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_cookie_file_no_record(self, mock_db_session, monkeypatch):
        """Verify returns None if no active cookie record exists in DB."""
        monkeypatch.setattr(settings.cookies, "enabled", True)
        
        # Ensure we are testing a supported platform
        result = await cookie_manager.get_cookie_file("youtube")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_cookie_file_success(self, mock_db_session, monkeypatch, tmp_path):
        """Verify returns path if active cookie exists and file exists on disk."""
        monkeypatch.setattr(settings.cookies, "enabled", True)
        
        db_session = mock_db_session
        platform = "youtube"
        filename = "test_cookie.txt"
        cookie_dir = tmp_path / platform
        cookie_dir.mkdir(parents=True)
        cookie_file_path = cookie_dir / filename
        cookie_file_path.write_text("dummy content")
        
        monkeypatch.setattr(settings.cookies, "path", tmp_path)
        
        # Create DB record
        cookie_record = CookieFile(
            platform=platform,
            filename=filename,
            is_active=True,
            uploaded_by_user_id=uuid.uuid4()
        )
        db_session.add(cookie_record)
        await db_session.commit()
        
        result = await cookie_manager.get_cookie_file(platform)
        assert result == str(cookie_file_path)

    def test_platform_key_mapping(self):
        """Test domain to platform mapping logic."""
        assert cookie_manager._platform_key("youtube.com") == "youtube"
        assert cookie_manager._platform_key("www.youtube.com") == "youtube"
        assert cookie_manager._platform_key("m.youtube.com") == "youtube"
        assert cookie_manager._platform_key("youtu.be") == "youtube"
        assert cookie_manager._platform_key("instagram.com") == "instagram"
        assert cookie_manager._platform_key("x.com") == "twitter"
        assert cookie_manager._platform_key("tiktok.com") == "tiktok"
        assert cookie_manager._platform_key("unknown.com") == "unknown.com"
