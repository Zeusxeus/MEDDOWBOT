from __future__ import annotations

import hashlib
import uuid

import structlog
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from cache.client import get_redis
from config.settings import settings
from database import crud
from database.models import JobStatus
from database.session import get_db
from task_queue.broker import broker
from utils.bot import get_bot, notify_user
from utils.ytdlp import (
    YtDlpAuthError,
    YtDlpExtractError,
    fetch_metadata,
    get_format_selector,
    select_best_format,
)
from workers.download import download_task

log = structlog.get_logger(__name__)


@broker.task(task_name="preflight", max_retries=2, timeout=35)
async def preflight_task(
    url: str,
    user_id_str: str,
    job_id_str: str,
    format_quality: str,
    chat_id: int,
    message_id: int,
) -> None:
    """
    Fast metadata worker. Performs cache check, extracts metadata,
    validates file size, and chains to download worker.
    """
    job_id = uuid.UUID(job_id_str)

    # Ensure required directories exist
    settings.disk.downloads_path.mkdir(parents=True, exist_ok=True)
    settings.disk.temp_path.mkdir(parents=True, exist_ok=True)
    settings.cookies.cookies_dir.mkdir(parents=True, exist_ok=True)

    # 1. Content-aware cache check
    # Include quality in hash so different quality requests don't hit same cache
    url_hash = hashlib.sha256(f"{url}:{format_quality}".encode()).hexdigest()

    async with get_db() as session:
        from sqlalchemy import select

        from database.models import DownloadJob

        # Query for a completed job with same url_hash and a valid telegram_file_id
        stmt = (
            select(DownloadJob)
            .where(
                DownloadJob.url_hash == url_hash,
                DownloadJob.status == JobStatus.DONE,
                DownloadJob.telegram_file_id.isnot(None),
            )
            .order_by(DownloadJob.completed_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        cached_job = result.scalar_one_or_none()

        if cached_job:
            log.info("cache_hit", url_hash=url_hash, job_id=job_id_str)
            await _deliver_cached_result(cached_job, job_id, chat_id, message_id)
            return

    # 2. Fetch metadata from yt-dlp
    try:
        preflight = await fetch_metadata(url, format_quality)
    except YtDlpAuthError as e:
        log.error("preflight_auth_error", job_id=job_id_str, error=str(e))
        await _fail_job(
            job_id, "Authentication required. Admin needs to set up cookies.", "YtDlpAuthError"
        )
        await notify_user(
            chat_id,
            message_id,
            "❌ This video requires authentication. Please notify the administrator to update cookies.",
        )
        return
    except YtDlpExtractError as e:
        log.error("preflight_extract_error", job_id=job_id_str, error=str(e))
        await _fail_job(job_id, f"Failed to extract metadata: {e}", "YtDlpExtractError")
        await notify_user(chat_id, message_id, f"❌ Could not get video info: {e}")
        return
    except Exception as e:
        log.exception("preflight_unexpected_error", job_id=job_id_str)
        await _fail_job(job_id, str(e), "UnexpectedError")
        await notify_user(chat_id, message_id, "❌ An unexpected error occurred.")
        return

    # 3. Update job in DB
    async with get_db() as session:
        await crud.update_job_status(
            session,
            job_id,
            JobStatus.RUNNING,
            url_hash=url_hash,
            platform=preflight.platform,
        )

    # 4. Cache preflight title in Redis for 1 hour
    redis = get_redis()
    title_cache_key = f"title:{url_hash}"
    await redis.set(title_cache_key, preflight.title, ex=3600)

    # 5. Large file warning
    best_format = select_best_format(preflight.formats, format_quality)

    filesize_bytes = best_format.filesize if best_format else None
    estimated_size_mb = filesize_bytes / (1024 * 1024) if filesize_bytes else 0

    if estimated_size_mb > settings.ffmpeg.large_file_warn_mb:
        log.info("large_file_warning", job_id=job_id_str, size_mb=estimated_size_mb)

        # Store job_id in Redis for confirmation
        confirm_key = f"confirm:{chat_id}:{message_id}"
        await redis.set(confirm_key, job_id_str, ex=300)

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"✅ Yes download ({int(estimated_size_mb)}MB)",
                        callback_data=f"confirm_dl:{job_id_str}",
                    ),
                    InlineKeyboardButton(text="❌ Cancel", callback_data=f"cancel_dl:{job_id_str}"),
                ]
            ]
        )

        await notify_user(
            chat_id,
            message_id,
            f"⚠️ <b>Large File Warning</b>\n\n"
            f"The estimated size is <b>{int(estimated_size_mb)}MB</b>. "
            f"This might take a while to process and upload.\n\n"
            f"Do you want to proceed?",
            reply_markup=kb,
        )
        return

    # 6. Success -> chain to download task
    format_selector = get_format_selector(url, format_quality)
    await download_task.kiq(
        url=url,
        user_id_str=user_id_str,
        job_id_str=job_id_str,
        format_selector=format_selector,
        format_quality=format_quality,
        chat_id=chat_id,
        message_id=message_id,
    )


async def _deliver_cached_result(
    cached_job: any, current_job_id: uuid.UUID, chat_id: int, message_id: int
) -> None:
    """Send existing Telegram file_id to user."""
    bot = get_bot()

    # Send the existing file_id
    await bot.send_document(
        chat_id=chat_id,
        document=cached_job.telegram_file_id,
        caption=f"✅ <b>(Cached) {cached_job.filename}</b>",
    )

    # Optional: cleanup the original request message
    if message_id > 0:
        try:
            await bot.delete_message(chat_id, message_id)
        except Exception:
            pass

    # 3. Update current job as DONE
    async with get_db() as session:
        await crud.update_job_status(
            session,
            current_job_id,
            JobStatus.DONE,
            telegram_file_id=cached_job.telegram_file_id,
            filename=cached_job.filename,
            size_bytes=cached_job.size_bytes,
            platform=cached_job.platform,
        )


async def _fail_job(job_id: uuid.UUID, error: str, error_type: str) -> None:
    """Update job status to FAILED in DB."""
    async with get_db() as session:
        await crud.update_job_status(
            session, job_id, JobStatus.FAILED, error_message=error, error_type=error_type
        )
