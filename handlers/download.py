from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from database import crud
from database.session import get_db
from workers.preflight import preflight_task

if TYPE_CHECKING:
    from database.models import User, UserSettings

router = Router(name="download")

URL_PATTERN = re.compile(r"https?://\S+")


async def _process_download(message: Message, db_user: User, user_settings: UserSettings, url: str):
    """Internal helper to create job and enqueue task."""
    # Create job in DB
    async with get_db() as session:
        job = await crud.create_download_job(
            session, db_user.id, url, user_settings.format_quality
        )

    # Reply to user
    short_url = f"{url[:60]}..." if len(url) > 60 else url
    queued_msg = await message.reply(
        f"⏳ <b>Queued</b>\n"
        f"🔗 {short_url}\n"
        f"📊 Quality: {user_settings.format_quality}\n"
        f"🆔 Job: <code>{str(job.id)[:8]}</code>",
    )

    # Enqueue preflight task
    await preflight_task.kiq(
        url=url,
        user_id_str=str(db_user.id),
        job_id_str=str(job.id),
        format_quality=user_settings.format_quality,
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
