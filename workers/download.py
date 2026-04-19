from __future__ import annotations

import asyncio
import os
import shutil
import socket
import time
import uuid
from datetime import UTC, datetime

import structlog

from bot.main import bot
from cache.progress import publish_progress, start_progress_listener
from config.settings import settings
from database import crud
from database.models import JobStatus
from database.session import get_db
from observability import metrics
from queues.broker import broker
from utils.ffmpeg import compress_video, needs_compression
from utils.quota import (
    DiskSpaceError,
    QuotaError,
    check_disk_space,
    check_and_increment_concurrent,
    decrement_concurrent,
)
from utils.upload import upload_file
from utils.ytdlp import YtDlpAuthError, YtDlpDownloadError, download_media

log = structlog.get_logger(__name__)


@broker.task(task_name="download", max_retries=3, retry_delay=30, timeout=600)
async def download_task(
    url: str,
    user_id_str: str,
    job_id_str: str,
    format_selector: str,
    format_quality: str,
    chat_id: int,
    message_id: int,
) -> None:
    """
    Main download pipeline worker.
    """
    start_time = time.monotonic()
    job_id = uuid.UUID(job_id_str)
    user_uuid = uuid.UUID(user_id_str)
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    tmp_dir = settings.disk.temp_path / job_id_str
    progress_task = None

    log.info("download_task_started", job_id=job_id_str, user_id=user_id_str)

    try:
        # 1. check_disk_space()
        await check_disk_space()

        # 2. check_and_increment_concurrent(user_id_str)
        # Note: The user prompt asked for user_id_str, which is the telegram_id string usually,
        # but in our context it's the internal user UUID string. 
        # utils/quota.py uses it as a redis key suffix.
        await check_and_increment_concurrent(user_id_str)

        # 3. Update job: status=RUNNING
        async with get_db() as session:
            await crud.update_job_status(
                session,
                job_id,
                JobStatus.RUNNING,
                claimed_by=worker_id,
                heartbeat_at=datetime.now(UTC),
            )

        # 4. mkdir /tmp/bot/{job_id}/
        tmp_dir.mkdir(parents=True, exist_ok=True)

        # 5. Create progress callback that publishes to Redis
        def progress_callback(d: dict) -> None:
            if d.get("status") == "downloading":
                p = d.get("_percent_str", "0%").replace("%", "")
                try:
                    percent = float(p)
                except ValueError:
                    percent = 0.0
                
                speed = d.get("_speed_str", "N/A")
                eta = d.get("_eta_str", "N/A")
                
                # We need to run this async, but the callback is sync called from thread
                loop = asyncio.get_event_loop()
                loop.create_task(publish_progress(job_id_str, percent, speed, eta))

        # 6. Start start_progress_listener() as asyncio Task
        progress_task = asyncio.create_task(
            start_progress_listener(job_id_str, bot, chat_id, message_id)
        )

        # 7. download_media()
        download_result = await download_media(
            url=url,
            output_dir=tmp_dir,
            format_selector=format_selector,
            job_id=job_id,
            progress_callback=progress_callback,
        )

        # 8. Check if needs compression
        # if local API disabled AND file > max_size_mb
        # max_size_mb is in FFmpegSettings
        max_bytes = settings.ffmpeg.max_size_mb * 1024 * 1024
        file_to_upload = download_result.file_path
        
        if not settings.bot.use_local_api and needs_compression(file_to_upload, max_bytes):
            # 9. If compression needed
            async with get_db() as session:
                await crud.update_job_status(
                    session,
                    job_id,
                    JobStatus.RUNNING,
                    heartbeat_at=datetime.now(UTC),
                )
            
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="⚙️ <b>Compressing video...</b> (this may take a few minutes)"
            )
            
            # Cancel progress task as it's for downloading
            if progress_task:
                progress_task.cancel()
            
            file_to_upload = await compress_video(file_to_upload, settings.ffmpeg.target_mb)

        # 10. Edit message: "📤 Uploading..."
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="📤 <b>Uploading to Telegram...</b>"
        )

        # 11. upload_file()
        file_id = await upload_file(
            chat_id=chat_id,
            file_path=file_to_upload,
            caption=f"✅ <b>{download_result.filename}</b>"
        )

        # 12. Update DB: status=DONE
        async with get_db() as session:
            await crud.update_job_status(
                session,
                job_id,
                JobStatus.DONE,
                telegram_file_id=file_id,
                filename=download_result.filename,
                size_bytes=file_to_upload.stat().st_size,
            )

            # 13. Update user: total_downloads++, total_bytes_served+=size
            await crud.increment_user_stats(
                session,
                user_uuid,
                file_to_upload.stat().st_size
            )

        # 14. Delete the "Uploading..." message
        try:
            await bot.delete_message(chat_id, message_id)
        except Exception:
            pass

        # 15. Record Prometheus metrics
        metrics.jobs_completed_total.labels(platform=download_result.platform).inc()
        metrics.bytes_served_total.inc(file_to_upload.stat().st_size)
        metrics.job_duration_seconds.observe(time.monotonic() - start_time)

    except DiskSpaceError as e:
        log.error("download_disk_error", job_id=job_id_str, error=str(e))
        await _fail_and_notify(job_id, chat_id, message_id, f"❌ Disk space error: {e}", "DiskSpaceError")
        raise  # Re-raise for Taskiq retry
    except YtDlpAuthError as e:
        log.error("download_auth_error", job_id=job_id_str, error=str(e))
        await _fail_and_notify(job_id, chat_id, message_id, "❌ Authentication error. Cookies might be expired.", "YtDlpAuthError")
        return  # Don't retry
    except YtDlpDownloadError as e:
        log.error("download_failed", job_id=job_id_str, error=str(e))
        # Get retry info
        # Taskiq retry count is not directly in the task args, but we can notify about it
        await _fail_and_notify(job_id, chat_id, message_id, f"❌ Download failed: {e}. Will retry if possible.", "YtDlpDownloadError")
        metrics.jobs_failed_total.labels(reason="download_error").inc()
        raise
    except QuotaError as e:
        log.warning("download_quota_error", job_id=job_id_str, error=str(e))
        await _fail_and_notify(job_id, chat_id, message_id, f"❌ Quota error: {e}", "QuotaError")
        return
    except Exception as e:
        log.exception("download_unexpected_error", job_id=job_id_str)
        await _fail_and_notify(job_id, chat_id, message_id, f"❌ Unexpected error: {e}", "UnexpectedError")
        metrics.jobs_failed_total.labels(reason="unexpected_error").inc()
        raise
    finally:
        # ALWAYS
        await decrement_concurrent(user_id_str)
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        if progress_task and not progress_task.done():
            progress_task.cancel()


async def _fail_and_notify(job_id: uuid.UUID, chat_id: int, message_id: int, text: str, error_type: str) -> None:
    """Helper to update DB and notify user on failure."""
    async with get_db() as session:
        await crud.update_job_status(
            session,
            job_id,
            JobStatus.FAILED,
            error_message=text,
            error_type=error_type
        )
    
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text
        )
    except Exception:
        await bot.send_message(chat_id, text)
