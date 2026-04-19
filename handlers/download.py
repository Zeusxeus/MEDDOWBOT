from __future__ import annotations

import re

import structlog
from aiogram import F, Router, types
from aiogram.filters import Command

from database import crud
from database.models import User
from database.session import get_db
from workers.preflight import preflight_task

log = structlog.get_logger(__name__)
router = Router()

URL_PATTERN = re.compile(r"https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*")


def extract_url(text: str | None) -> str | None:
    """Extract first URL from text."""
    if not text:
        return None
    match = URL_PATTERN.search(text)
    return match.group(0) if match else None


@router.message(Command("download"))
@router.message(F.text.regexp(URL_PATTERN))
async def handle_download(message: types.Message, db_user: User) -> types.Message | None:
    """Validate URL, create job, and enqueue preflight task."""
    url = extract_url(message.text)
    if not url:
        return await message.reply("❌ No valid URL found.")

    if not db_user.settings:
        return await message.reply("❌ Settings not found.")

    async with get_db() as session:
        job = await crud.create_download_job(
            session, db_user.id, url, db_user.settings.format_quality
        )

    sent = await message.reply(f"⏳ Job <code>{job.id}</code> queued. Extracting info...")
    await preflight_task.kiq(
        url=url,
        user_id_str=str(db_user.id),
        job_id_str=str(job.id),
        format_quality=db_user.settings.format_quality,
        chat_id=message.chat.id,
        message_id=sent.message_id,
    )
    return sent
