"""Tests for workers/preflight.py."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from database.models import DownloadJob, JobStatus
from utils.ytdlp import FormatInfo, PreflightResult, YtDlpAuthError, YtDlpExtractError
from workers.preflight import preflight_task


@pytest.fixture
def mock_bot(monkeypatch):
    """Provide a mock bot."""
    bot = AsyncMock()
    monkeypatch.setattr("workers.preflight.get_bot", lambda: bot)
    return bot


@pytest.fixture
def mock_download_task(monkeypatch):
    """Provide a mock download task kiq."""
    task = AsyncMock()
    monkeypatch.setattr("workers.preflight.download_task.kiq", task)
    return task


class TestPreflightWorker:
    """Tests for the preflight worker."""

    @pytest.mark.asyncio
    async def test_cache_hit(self, mock_db_session, mock_bot):
        """Test cache delivery when a job with same url_hash is already completed."""
        import hashlib
        from datetime import datetime

        url = "https://youtube.com/watch?v=123"
        quality = "1080"
        url_hash = hashlib.sha256(f"{url}{quality}".encode()).hexdigest()
        job_id = uuid.uuid4()
        cached_job_id = uuid.uuid4()

        # Add current job to DB
        current_job = DownloadJob(
            id=job_id,
            url=url,
            status=JobStatus.PENDING,
            user_id=uuid.uuid4(),
        )
        mock_db_session.add(current_job)

        # Add cached job to DB
        cached_job = DownloadJob(
            id=cached_job_id,
            url=url,
            status=JobStatus.DONE,
            user_id=uuid.uuid4(),
            url_hash=url_hash,
            telegram_file_id="cached_file_id_abc123",
            completed_at=datetime.utcnow()
        )
        mock_db_session.add(cached_job)
        await mock_db_session.commit()

        # Act
        await preflight_task(url, "1", str(job_id), quality, 123, 456)

        # Assert
        mock_bot.edit_message_text.assert_called_once()
        mock_bot.send_video.assert_called_once_with(
            chat_id=123,
            video="cached_file_id_abc123",
            caption="✅ Downloaded video\n(Delivered from cache)"
        )

        await mock_db_session.refresh(current_job)
        assert current_job.status == JobStatus.DONE
        assert current_job.telegram_file_id == "cached_file_id_abc123"

    @pytest.mark.asyncio
    @patch("workers.preflight.fetch_metadata")
    async def test_auth_error(self, mock_fetch, mock_db_session, mock_bot):
        """Test auth error handling during metadata fetch."""
        job_id = uuid.uuid4()
        current_job = DownloadJob(id=job_id, url="http://x", status=JobStatus.PENDING, user_id=uuid.uuid4())
        mock_db_session.add(current_job)
        await mock_db_session.commit()

        mock_fetch.side_effect = YtDlpAuthError("Sign in")

        await preflight_task("http://x", "1", str(job_id), "1080", 1, 1)

        await mock_db_session.refresh(current_job)
        assert current_job.status == JobStatus.FAILED
        assert current_job.error_type == "YtDlpAuthError"

        mock_bot.edit_message_text.assert_called_once()
        assert "requires authentication" in mock_bot.edit_message_text.call_args[1]["text"]

    @pytest.mark.asyncio
    @patch("workers.preflight.fetch_metadata")
    async def test_extract_error(self, mock_fetch, mock_db_session, mock_bot):
        """Test extract error handling during metadata fetch."""
        job_id = uuid.uuid4()
        current_job = DownloadJob(id=job_id, url="http://x", status=JobStatus.PENDING, user_id=uuid.uuid4())
        mock_db_session.add(current_job)
        await mock_db_session.commit()

        mock_fetch.side_effect = YtDlpExtractError("Not available")

        await preflight_task("http://x", "1", str(job_id), "1080", 1, 1)

        await mock_db_session.refresh(current_job)
        assert current_job.status == JobStatus.FAILED
        assert current_job.error_type == "YtDlpExtractError"

    @pytest.mark.asyncio
    @patch("workers.preflight.fetch_metadata")
    async def test_large_file_warning(self, mock_fetch, mock_db_session, mock_bot, redis_client):
        """Test large file warning flow."""
        job_id = uuid.uuid4()
        current_job = DownloadJob(id=job_id, url="http://x", status=JobStatus.PENDING, user_id=uuid.uuid4())
        mock_db_session.add(current_job)
        await mock_db_session.commit()

        # Large filesize > settings.ffmpeg.large_file_warn_mb (e.g., 60MB, assuming default > 50)
        from config.settings import settings
        large_size = (settings.ffmpeg.large_file_warn_mb + 10) * 1024 * 1024

        mock_fetch.return_value = PreflightResult(
            url="http://x",
            title="Large Video",
            thumbnail=None,
            duration=600,
            formats=[FormatInfo(format_id="1", ext="mp4", vcodec="avc1", filesize=large_size, resolution="1920x1080")],
            platform="youtube",
            user_format_quality="best"
        )

        await preflight_task("http://x", "1", str(job_id), "best", 1, 1)

        await mock_db_session.refresh(current_job)
        assert current_job.status == JobStatus.RUNNING

        mock_bot.edit_message_text.assert_called_once()
        assert "Large File Warning" in mock_bot.edit_message_text.call_args[1]["text"]

        confirm_key = "confirm:1:1"
        assert await redis_client.get(confirm_key) == str(job_id)

    @pytest.mark.asyncio
    @patch("workers.preflight.fetch_metadata")
    async def test_normal_flow(self, mock_fetch, mock_db_session, mock_bot, mock_download_task):
        """Test normal flow chaining to download worker."""
        job_id = uuid.uuid4()
        current_job = DownloadJob(id=job_id, url="http://x", status=JobStatus.PENDING, user_id=uuid.uuid4())
        mock_db_session.add(current_job)
        await mock_db_session.commit()

        small_size = 10 * 1024 * 1024

        mock_fetch.return_value = PreflightResult(
            url="http://x",
            title="Small Video",
            thumbnail=None,
            duration=60,
            formats=[FormatInfo(format_id="1", ext="mp4", vcodec="avc1", filesize=small_size, resolution="1280x720")],
            platform="youtube",
            user_format_quality="720"
        )

        await preflight_task("http://x", "1", str(job_id), "720", 1, 1)

        await mock_db_session.refresh(current_job)
        assert current_job.status == JobStatus.RUNNING

        mock_bot.edit_message_text.assert_called_once()
        assert "Downloading" in mock_bot.edit_message_text.call_args[1]["text"]

        mock_download_task.assert_called_once()
