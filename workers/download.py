from __future__ import annotations

import asyncio
import shutil
import uuid
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
from utils.bot import get_bot, notify_user
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
        # 3. Update status: "⏬ Downloading..."
        message_id = await notify_user(
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
        # Get user's custom limit from DB
        async with get_db() as session:
            from database.models import User
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            
            user_uuid = uuid.UUID(user_id_str)
            stmt = select(User).where(User.id == user_uuid).options(selectinload(User.settings))
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            
            user_settings = user.settings if user else None
            user_limit_mb = user_settings.max_file_size if user_settings else settings.ffmpeg.max_size_mb
            as_video = user_settings.upload_as_video if user_settings else False

        max_bytes = user_limit_mb * 1024 * 1024
        file_to_upload = download_result.file_path
        
        # Determine if we should bypass the 50MB limit
        # Local Bot API allows up to 2GB (2000MB)
        is_large_file = file_to_upload.stat().st_size > (2000 * 1024 * 1024)
        
        log.info("checking_compression", 
                 path=str(file_to_upload), 
                 size=file_to_upload.stat().st_size, 
                 limit_mb=user_limit_mb,
                 local_api=settings.local_api.enabled)

        # Trigger compression ONLY if:
        # 1. Local Bot API is NOT enabled AND file > user limit (usually 50MB)
        # OR
        # 2. File is somehow > 2GB (Telegram's absolute limit even for local API)
        should_compress = False
        if not settings.local_api.enabled and needs_compression(file_to_upload, max_bytes):
            should_compress = True
        elif settings.local_api.enabled and is_large_file:
            should_compress = True

        if should_compress:
            # 8. If compression needed
            log.info("compression_triggered", path=str(file_to_upload))
            async with get_db() as session:
                await crud.update_job_status(
                    session,
                    job_id,
                    JobStatus.RUNNING,
                    heartbeat_at=datetime.now(UTC),
                )

            await notify_user(
                chat_id=chat_id,
                message_id=message_id,
                text="⚙️ <b>Compressing video...</b> (this may take a few minutes)",
            )

            # Cancel progress task as it's for downloading
            if progress_task:
                progress_task.cancel()

            file_to_upload = await compress_video(file_to_upload, settings.ffmpeg.target_mb)
            log.info("compression_finished", new_path=str(file_to_upload), new_size=file_to_upload.stat().st_size)

        # 9. Edit message: "📤 Uploading..."
        await notify_user(
            chat_id=chat_id, message_id=message_id, text="📤 <b>Uploading to Telegram...</b>"
        )

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
                telegram_file_id=file_id,
                filename=download_result.filename,
                size_bytes=download_result.size_bytes,
                platform=download_result.platform,
            )

        await notify_user(chat_id=chat_id, message_id=message_id, text="✅ <b>Download complete!</b>")

    except Exception as e:
        log.exception("download_task_failed", job_id=job_id_str, error=str(e))
        async with get_db() as session:
            await crud.update_job_status(
                session,
                job_id,
                JobStatus.FAILED,
                error_message=str(e),
                error_type=type(e).__name__,
            )

        await notify_user(
            chat_id=chat_id,
            message_id=message_id,
            text=f"❌ <b>Download failed</b>\n\nURL: <code>{url}</code>\nError: <code>{str(e)[:200]}</code>",
        )

    finally:
        if progress_task:
            progress_task.cancel()
        # 12. Cleanup temp directory
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception as e:
            log.error("cleanup_failed", path=str(tmp_dir), error=str(e))
