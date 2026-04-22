"""Tests for utils/ytdlp.py."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from yt_dlp.utils import DownloadError

from utils.ytdlp import (
    FormatInfo,
    YtDlpAuthError,
    YtDlpDownloadError,
    YtDlpExtractError,
    download_media,
    fetch_metadata,
    get_format_selector,
    select_best_format,
)


class TestYtDlp:
    """Tests for yt-dlp utility functions."""

    def test_get_format_selector(self):
        """Test format selector logic based on platform and quality."""
        assert get_format_selector("https://youtube.com/watch?v=123", "audio") == "bestaudio/best"
        assert (
            get_format_selector("https://youtube.com/watch?v=123", "1080")
            == "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        )
        assert get_format_selector("https://tiktok.com/@user/video/123", "best") == "best[ext=mp4]/best"
        assert get_format_selector("https://example.com/video", "best") == "best[ext=mp4]/best"

    def test_select_best_format_audio(self):
        """Test selecting the best audio format."""
        formats = [
            FormatInfo(format_id="1", ext="m4a", vcodec="none", filesize=1000),
            FormatInfo(format_id="2", ext="m4a", vcodec="none", filesize=2000),
            FormatInfo(format_id="3", ext="mp4", vcodec="avc1", filesize=5000),
        ]
        best = select_best_format(formats, "audio")
        assert best is not None
        assert best.format_id == "2"

    def test_select_best_format_video(self):
        """Test selecting the best video format based on quality."""
        formats = [
            FormatInfo(format_id="1", ext="mp4", vcodec="avc1", filesize=1000, resolution="1280x720"),
            FormatInfo(format_id="2", ext="mp4", vcodec="avc1", filesize=2000, resolution="1920x1080"),
            FormatInfo(format_id="3", ext="mp4", vcodec="avc1", filesize=500, resolution="854x480"),
        ]
        
        # Test 1080p
        best_1080 = select_best_format(formats, "1080")
        assert best_1080 is not None
        assert best_1080.format_id == "2"

        # Test 720p
        best_720 = select_best_format(formats, "720")
        assert best_720 is not None
        assert best_720.format_id == "1"

        # Test fallback
        best_invalid = select_best_format(formats, "invalid_quality")
        assert best_invalid is None

    @pytest.mark.asyncio
    @patch("utils.ytdlp.proxy_pool.get_proxy_for_url", new_callable=AsyncMock)
    @patch("utils.ytdlp.cookie_manager.get_cookie_file", new_callable=AsyncMock)
    @patch("utils.ytdlp.yt_dlp.YoutubeDL")
    async def test_fetch_metadata_success(self, mock_ytdl_class, mock_get_cookie, mock_get_proxy):
        """Test successful metadata fetching."""
        mock_get_cookie.return_value = None
        mock_get_proxy.return_value = None
        mock_ytdl = MagicMock()
        mock_ytdl.__enter__.return_value = mock_ytdl
        mock_ytdl.extract_info.return_value = {
            "title": "Test Video",
            "thumbnail": "http://example.com/thumb.jpg",
            "duration": 120,
            "extractor": "youtube",
            "formats": [
                {"format_id": "1", "ext": "mp4", "vcodec": "avc1", "width": 1920, "height": 1080, "filesize": 1024}
            ],
        }
        mock_ytdl_class.return_value = mock_ytdl

        result = await fetch_metadata("https://youtube.com/watch?v=123", "1080")
        
        assert result.title == "Test Video"
        assert result.platform == "youtube"
        assert len(result.formats) == 1
        assert result.formats[0].resolution == "1920x1080"

    @pytest.mark.asyncio
    @patch("utils.ytdlp.proxy_pool.get_proxy_for_url", new_callable=AsyncMock)
    @patch("utils.ytdlp.cookie_manager.get_cookie_file", new_callable=AsyncMock)
    @patch("utils.ytdlp.yt_dlp.YoutubeDL")
    async def test_fetch_metadata_auth_error(self, mock_ytdl_class, mock_get_cookie, mock_get_proxy):
        """Test metadata fetching with auth error."""
        mock_get_cookie.return_value = None
        mock_get_proxy.return_value = None
        mock_ytdl = MagicMock()
        mock_ytdl.__enter__.return_value = mock_ytdl
        mock_ytdl.extract_info.side_effect = DownloadError("Sign in to confirm your age")
        mock_ytdl_class.return_value = mock_ytdl

        with pytest.raises(YtDlpAuthError, match="Authentication required"):
            await fetch_metadata("https://youtube.com/watch?v=123", "1080")

    @pytest.mark.asyncio
    @patch("utils.ytdlp.proxy_pool.get_proxy_for_url", new_callable=AsyncMock)
    @patch("utils.ytdlp.cookie_manager.get_cookie_file", new_callable=AsyncMock)
    @patch("utils.ytdlp.yt_dlp.YoutubeDL")
    async def test_fetch_metadata_extract_error(self, mock_ytdl_class, mock_get_cookie, mock_get_proxy):
        """Test metadata fetching with generic extract error."""
        mock_get_cookie.return_value = None
        mock_get_proxy.return_value = None
        mock_ytdl = MagicMock()
        mock_ytdl.__enter__.return_value = mock_ytdl
        mock_ytdl.extract_info.side_effect = DownloadError("Video not available")
        mock_ytdl_class.return_value = mock_ytdl

        with pytest.raises(YtDlpExtractError, match="Video is unavailable"):
            await fetch_metadata("https://youtube.com/watch?v=123", "1080")

    @pytest.mark.asyncio
    @patch("utils.ytdlp.proxy_pool.get_proxy_for_url", new_callable=AsyncMock)
    @patch("utils.ytdlp.cookie_manager.get_cookie_file", new_callable=AsyncMock)
    @patch("utils.ytdlp.yt_dlp.YoutubeDL")
    async def test_download_media_success(self, mock_ytdl_class, mock_get_cookie, mock_get_proxy, tmp_path):
        """Test successful media download."""
        mock_get_cookie.return_value = None
        mock_get_proxy.return_value = None
        test_file = tmp_path / "Test Video.mp4"
        test_file.write_text("fake video content")

        mock_ytdl = MagicMock()
        mock_ytdl.__enter__.return_value = mock_ytdl
        mock_ytdl.extract_info.return_value = {
            "_filename": str(test_file),
            "duration": 120,
            "thumbnail": "http://example.com/thumb.jpg",
            "extractor": "youtube",
        }
        mock_ytdl_class.return_value = mock_ytdl

        async def dummy_callback(d):
            pass

        import uuid
        job_id = uuid.uuid4()

        result = await download_media(
            "https://youtube.com/watch?v=123",
            tmp_path,
            "best[ext=mp4]/best",
            job_id,
            dummy_callback
        )

        assert result.file_path == test_file
        assert result.filename == "Test Video.mp4"
        assert result.duration == 120

    @pytest.mark.asyncio
    @patch("utils.ytdlp.proxy_pool.get_proxy_for_url", new_callable=AsyncMock)
    @patch("utils.ytdlp.cookie_manager.get_cookie_file", new_callable=AsyncMock)
    @patch("utils.ytdlp.yt_dlp.YoutubeDL")
    async def test_download_media_error(self, mock_ytdl_class, mock_get_cookie, mock_get_proxy, tmp_path):
        """Test media download failure."""
        mock_get_cookie.return_value = None
        mock_get_proxy.return_value = None
        mock_ytdl = MagicMock()
        mock_ytdl.__enter__.return_value = mock_ytdl
        mock_ytdl.extract_info.side_effect = DownloadError("Connection refused")
        mock_ytdl_class.return_value = mock_ytdl

        async def dummy_callback(d):
            pass

        import uuid
        job_id = uuid.uuid4()

        with pytest.raises(YtDlpDownloadError):
            await download_media(
                "https://youtube.com/watch?v=123",
                tmp_path,
                "best[ext=mp4]/best",
                job_id,
                dummy_callback
            )
