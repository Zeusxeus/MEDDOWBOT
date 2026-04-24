from __future__ import annotations

import sys
import pathlib
from typing import Any, Optional

from aiogram import Bot, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

from config.settings import settings

_worker_bot: Bot | None = None


def get_bot() -> Bot:
    """
    Get bot instance. 
    Uses the one from bot.main if available (main process), 
    otherwise creates and caches a fresh one (worker process).
    """
    global _worker_bot
    if _worker_bot is not None:
        return _worker_bot

    try:
        # Ensure project root is in path for imports
        root = str(pathlib.Path(__file__).parent.parent)
        if root not in sys.path:
            sys.path.append(root)
            
        from bot.main import bot_instance
        if bot_instance is not None:
            _worker_bot = bot_instance
            return _worker_bot
    except (ModuleNotFoundError, ImportError, AttributeError):
        pass

    # No bot_instance found, create a new one (likely in a worker process)
    bot_kwargs: dict[str, Any] = {"default": DefaultBotProperties(parse_mode=ParseMode.HTML)}
    
    if settings.local_api.enabled:
        # Reconstruct base_url for Local Bot API
        bot_kwargs["base_url"] = f"{settings.local_api.url}/bot"
        
    _worker_bot = Bot(token=settings.bot.token, **bot_kwargs)
    return _worker_bot


async def notify_user(
    chat_id: int, 
    message_id: int, 
    text: str, 
    reply_markup: Optional[types.InlineKeyboardMarkup] = None
) -> int:
    """
    Edit an existing message or send a new one if message_id is 0 or editing fails.
    Returns the message_id of the sent/edited message.
    """
    bot = get_bot()
    
    if message_id > 0:
        try:
            msg = await bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
            return msg.message_id if isinstance(msg, types.Message) else message_id
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                return message_id
            # If message to edit not found or other bad request, fall back to sending new
            pass
        except Exception:
            pass

    # Send new message as fallback
    msg = await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode="HTML"
    )
    return msg.message_id
