from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from database import crud
from database.session import get_db
from workers.preflight import preflight_task

if TYPE_CHECKING:
    from database.models import User, UserSettings

router = Router(name="download")

URL_PATTERN = re.compile(r"https?://\S+")


async def _process_download(message: Message, db_user: User, user_settings: UserSettings, url: str):
    """Internal helper to create job and enqueue task."""
    url_lower = url.lower()
    is_youtube = "youtube.com" in url_lower or "youtu.be" in url_lower
    
    # For YouTube, we start with 'best' to trigger quality menu in preflight
    # For others, we use the user's default setting
    quality = "best" if is_youtube else user_settings.format_quality

    # Create job in DB
    async with get_db() as session:
        job = await crud.create_download_job(
            session, db_user.id, url, quality
        )

    # Reply to user
    short_url = f"{url[:60]}..." if len(url) > 60 else url
    
    status_text = f"⏳ <b>Queued</b>\n🔗 {short_url}\n🆔 Job: <code>{str(job.id)[:8]}</code>"
    if not is_youtube:
        status_text += f"\n📊 Quality: {quality}"

    queued_msg = await message.reply(status_text)

    # Enqueue preflight task
    await preflight_task.kiq(
        url=url,
        user_id_str=str(db_user.id),
        job_id_str=str(job.id),
        format_quality=quality,
        chat_id=message.chat.id,
        message_id=queued_msg.message_id,
    )


@router.message(Command("download"))
@router.message(F.text.regexp(URL_PATTERN))
async def handle_download(message: Message, db_user: User, user_settings: UserSettings):
    """Handle /download command or raw URL message."""
    text = message.text or ""
    url_match = URL_PATTERN.search(text)
    url = url_match.group(0) if url_match else ""

    if not url or not (parsed := urlparse(url)).scheme or not parsed.netloc:
        await message.reply("❌ Please provide a valid URL.")
        return

    await _process_download(message, db_user, user_settings, url)


@router.callback_query(lambda c: c.data and c.data.startswith("dl_q:"))
async def handle_quality_selection(callback: CallbackQuery, db_user: User):
    """Handle quality selection from the preflight menu."""
    # Format: dl_q:job_id:quality
    parts = callback.data.split(":")
    if len(parts) < 3:
        return

    job_id_str = parts[1]
    quality = parts[2]

    await callback.message.edit_text(f"🚀 Quality selected: <b>{quality}</b>. Starting download...")

    async with get_db() as session:
        from database.models import DownloadJob
        import uuid
        job_uuid = uuid.UUID(job_id_str)
        job = await session.get(DownloadJob, job_uuid)
        if not job:
            await callback.answer("❌ Job not found.")
            return

        # Update job with selected quality
        job.format_requested = quality
        await session.commit()

        # Re-enqueue preflight with the specific quality
        # This will skip the menu now because quality != 'best'
        await preflight_task.kiq(
            url=job.url,
            user_id_str=str(db_user.id),
            job_id_str=job_id_str,
            format_quality=quality,
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
        )
    
    await callback.answer()
