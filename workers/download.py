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
from utils.archiver import create_split_archive

log = structlog.get_logger(__name__)


@broker.task(task_name="download", max_retries=3, timeout=1200) # Increased timeout for large files/HEVC
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
        # Get user's custom limit and toggle from DB
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
            compression_enabled = user_settings.compression_enabled if user_settings else True

        max_bytes = user_limit_mb * 1024 * 1024
        file_to_upload = download_result.file_path
        
        log.info("checking_compression", 
                 path=str(file_to_upload), 
                 size=file_to_upload.stat().st_size, 
                 limit_mb=user_limit_mb,
                 compression_enabled=compression_enabled)

        # Trigger compression ONLY if enabled by user AND file > user limit
        if compression_enabled and needs_compression(file_to_upload, max_bytes):
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
                text="⚙️ <b>Compressing video to HEVC...</b> (this may take a few minutes)",
            )

            # Cancel progress task as it's for downloading
            if progress_task:
                progress_task.cancel()

            file_to_upload = await compress_video(file_to_upload, user_limit_mb)
            log.info("compression_finished", new_path=str(file_to_upload), new_size=file_to_upload.stat().st_size)

        # 9. CHECK FOR 2GB LIMIT AND SPLIT IF NEEDED
        # Telegram Local API allows up to 2GB, but we split at 1900MB for safety
        TELEGRAM_LIMIT_BYTES = 1900 * 1024 * 1024
        files_to_upload = [file_to_upload]
        
        if file_to_upload.stat().st_size > TELEGRAM_LIMIT_BYTES:
            log.info("splitting_large_file", size=file_to_upload.stat().st_size)
            await notify_user(
                chat_id=chat_id,
                message_id=message_id,
                text="📦 <b>File is over 2GB. Splitting into 7z parts...</b>"
            )
            files_to_upload = await create_split_archive(file_to_upload, part_size_mb=1900)

        # 10. upload_file() loop
        await notify_user(
            chat_id=chat_id, message_id=message_id, text=f"📤 <b>Uploading {len(files_to_upload)} file(s) to Telegram...</b>"
        )

        last_file_id = None
        for i, f_path in enumerate(files_to_upload):
            if len(files_to_upload) > 1:
                await notify_user(
                    chat_id=chat_id, message_id=message_id, 
                    text=f"📤 <b>Uploading part {i+1}/{len(files_to_upload)}...</b>"
                )
            
            # Determine if this part should be uploaded as video
            # Only the main file (if not split) should be video media if requested.
            # 7z parts should always be documents.
            is_part_video = as_video if len(files_to_upload) == 1 else False
            
            caption = f"✅ <b>{f_path.name}</b>"
            if len(files_to_upload) > 1:
                caption += f" (Part {i+1}/{len(files_to_upload)})"

            last_file_id = await upload_file(
                chat_id=chat_id,
                file_path=f_path,
                caption=caption,
                as_video=is_part_video,
                thumbnail=Path(download_result.thumbnail_url) if download_result.thumbnail_url and Path(download_result.thumbnail_url).exists() and i == 0 else None,
                duration=download_result.duration if i == 0 else None,
            )

        # 11. Success
        async with get_db() as session:
            await crud.update_job_status(
                session,
                job_id,
                JobStatus.DONE,
                telegram_file_id=last_file_id, # Store last part's file_id or main file_id
                filename=download_result.filename,
                size_bytes=download_result.size_bytes,
                platform=download_result.platform,
            )

        await notify_user(chat_id=chat_id, message_id=message_id, text="✅ <b>All parts uploaded successfully!</b>")

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
