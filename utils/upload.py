from __future__ import annotations

from pathlib import Path

import structlog
from aiogram.types import FSInputFile

log = structlog.get_logger(__name__)


async def upload_file(chat_id: int, file_path: Path, caption: str) -> str:
    """
    Uploads a file to Telegram as a document.

    Args:
        chat_id: The Telegram chat ID to send the file to.
        file_path: The local path to the file.
        caption: The caption for the document.

    Returns:
        The telegram_file_id of the uploaded document.

    Raises:
        Exception: If the upload fails or bot is not initialized.
    """
    from bot.main import bot_instance
    bot = bot_instance

    log.info("uploading_file", chat_id=chat_id, path=str(file_path))

    if bot is None:
        log.error("bot_not_initialized")
        raise RuntimeError("Bot instance is not initialized")

    try:
        document = FSInputFile(path=file_path)
        message = await bot.send_document(
            chat_id=chat_id,
            document=document,
            caption=caption,
        )

        if not message.document:
            log.error("upload_failed_no_document_in_response", chat_id=chat_id)
            raise ValueError("No document in Telegram response")

        file_id = message.document.file_id
        log.info("upload_success", chat_id=chat_id, file_id=file_id)
        return file_id
    except Exception as e:
        log.error("upload_failed", chat_id=chat_id, error=str(e))
        raise
