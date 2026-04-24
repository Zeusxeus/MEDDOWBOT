from __future__ import annotations

from pathlib import Path
from typing import Optional

import structlog
from aiogram.types import FSInputFile

log = structlog.get_logger(__name__)


async def upload_file(
    chat_id: int, 
    file_path: Path, 
    caption: str, 
    as_video: bool = False,
    thumbnail: Optional[Path] = None,
    duration: Optional[int] = None,
) -> str:
    """
    Uploads a file to Telegram.

    Args:
        chat_id: The Telegram chat ID to send the file to.
        file_path: The local path to the file.
        caption: The caption for the document.
        as_video: Whether to upload as a video media (True) or document (False).
        thumbnail: Path to thumbnail image.
        duration: Video duration in seconds.

    Returns:
        The telegram_file_id of the uploaded file.
    """
    from utils.bot import get_bot
    bot = get_bot()

    log.info("uploading_file", chat_id=chat_id, path=str(file_path), as_video=as_video)

    if bot is None:
        log.error("bot_not_initialized")
        raise RuntimeError("Bot instance is not initialized")

    try:
        media_file = FSInputFile(path=file_path)
        thumb_file = FSInputFile(path=thumbnail) if thumbnail and thumbnail.exists() else None

        if as_video and file_path.suffix.lower() in [".mp4", ".mkv", ".mov"]:
            message = await bot.send_video(
                chat_id=chat_id,
                video=media_file,
                caption=caption,
                thumbnail=thumb_file,
                duration=duration,
                supports_streaming=True,
            )
            result_obj = message.video
        else:
            message = await bot.send_document(
                chat_id=chat_id,
                document=media_file,
                caption=caption,
                thumbnail=thumb_file,
            )
            result_obj = message.document

        if not result_obj:
            log.error("upload_failed_no_media_in_response", chat_id=chat_id)
            raise ValueError("No media object in Telegram response")

        file_id = result_obj.file_id
        log.info("upload_success", chat_id=chat_id, file_id=file_id)
        return file_id
    except Exception as e:
        log.error("upload_failed", chat_id=chat_id, error=str(e))
        raise
