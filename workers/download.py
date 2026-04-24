from __future__ import annotations

import asyncio
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import structlog

from cache.progress import publish_progress, start_progress_listener
from config.settings import settings
from database import crud
from database.models import JobStatus
from database.session import get_db
from task_queue.broker import broker
from utils.bot import get_bot
from utils.ffmpeg import compress_video, needs_compression
from utils.notify import notify_admins
from utils.upload import upload_file
from utils.ytdlp import download_media

log = structlog.get_logger(__name__)


@broker.task(task_name="download", max_retries=3, timeout=600)
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
    Taskiq task that handles the full download/process/upload lifecycle.
    """
    job_id = UUID(job_id_str)
    log.info("download_task_started", job_id=job_id_str, url=url)

    bot = get_bot()

    # 0. Check disk space
    settings.disk.downloads_path.mkdir(parents=True, exist_ok=True)
    settings.disk.temp_path.mkdir(parents=True, exist_ok=True)
    total, used, free = shutil.disk_usage(settings.disk.downloads_path)
    free_gb = free / (2**30)
    if free_gb < settings.disk.min_free_gb:
        log.error("low_disk_space", free_gb=free_gb)
        await notify_admins(
            bot,
            f"⚠️ <b>Low Disk Space!</b>\nFree: <code>{free_gb:.2f} GB</code>\nThreshold: <code>{settings.disk.min_free_gb} GB</code>",
        )

    # 1. Update job status to RUNNING
    async with get_db() as session:
        await crud.update_job_status(
            session,
            job_id,
            JobStatus.RUNNING,
            heartbeat_at=datetime.now(UTC),
        )

    # 2. Create temp directory for this job
    tmp_dir = Path(f"data/downloads/{job_id_str}")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    progress_task = None
    try:
        # 3. Edit message: "⏬ Downloading..."
        await bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text="⏬ <b>Downloading...</b> (0%)"
        )

        # 4. Create progress callback that publishes to Redis
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
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(publish_progress(job_id_str, percent, speed, eta))
                except RuntimeError:
                    pass

        # 5. Start start_progress_listener() as asyncio Task
        progress_task = asyncio.create_task(
            start_progress_listener(job_id_str, bot, chat_id, message_id)
        )

        # 6. download_media()
        download_result = await download_media(
            url=url,
            output_dir=tmp_dir,
            format_selector=format_selector,
            job_id=job_id,
            progress_callback=progress_callback,
        )

        # 7. Check if needs compression
        max_bytes = settings.ffmpeg.max_size_mb * 1024 * 1024
        file_to_upload = download_result.file_path

        if not settings.local_api.enabled and needs_compression(file_to_upload, max_bytes):
            # 8. If compression needed
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
                text="⚙️ <b>Compressing video...</b> (this may take a few minutes)",
            )

            # Cancel progress task as it's for downloading
            if progress_task:
                progress_task.cancel()

            file_to_upload = await compress_video(file_to_upload, settings.ffmpeg.target_mb)

        # 9. Edit message: "📤 Uploading..."
        await bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text="📤 <b>Uploading to Telegram...</b>"
        )

        # 10. upload_file()
        async with get_db() as session:
            user = await crud.get_user_by_telegram_id(session, int(user_id_str))
            user_settings = user.settings if user else None
            as_video = user_settings.upload_as_video if user_settings else False

        file_id = await upload_file(
            chat_id=chat_id,
            file_path=file_to_upload,
            caption=f"✅ <b>{download_result.filename}</b>",
            as_video=as_video,
            thumbnail=Path(download_result.thumbnail_url) if download_result.thumbnail_url and Path(download_result.thumbnail_url).exists() else None,
            duration=download_result.duration,
        )

        # 11. Success
        async with get_db() as session:
            await crud.update_job_status(
                session,
                job_id,
                JobStatus.DONE,
                heartbeat_at=datetime.now(UTC),
                telegram_file_id=file_id,
                size_bytes=file_to_upload.stat().st_size,
                filename=download_result.filename,
            )
            # Update user stats
            await crud.increment_user_stats(
                session,
                UUID(user_id_str),
                file_to_upload.stat().st_size,
            )

        # 12. Cleanup
        await bot.delete_message(chat_id=chat_id, message_id=message_id)

    except Exception as e:
        log.exception("download_task_failed", job_id=job_id_str, error=str(e))

        async with get_db() as session:
            await crud.update_job_status(
                session,
                job_id,
                JobStatus.FAILED,
                error_message=str(e)[:500],
            )

        await notify_admins(
            bot,
            f"❌ <b>Job Failed!</b>\nJob ID: <code>{job_id_str}</code>\nURL: {url}\nError: <code>{str(e)[:200]}</code>",
        )

        try:
            await bot.send_message(
                chat_id=chat_id,
                text=f"❌ <b>Download failed</b>\n\nURL: {url}\nError: <code>{str(e)[:200]}</code>",
            )
        except Exception:
            log.error("failed_to_send_error_message", chat_id=chat_id)

    finally:
        if progress_task and not progress_task.done():
            progress_task.cancel()

        # Cleanup temp files
        try:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir)
        except Exception:
            log.warning("cleanup_failed", path=str(tmp_dir))
