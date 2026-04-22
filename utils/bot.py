from __future__ import annotations

from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

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
        from bot.main import bot_instance
        if bot_instance is not None:
            _worker_bot = bot_instance
            return _worker_bot
    except (ModuleNotFoundError, ImportError):
        pass

    # No bot_instance found, create a new one (likely in a worker process)
    bot_kwargs: dict[str, Any] = {"default": DefaultBotProperties(parse_mode=ParseMode.HTML)}
    
    if settings.local_api.enabled:
        # Reconstruct base_url for Local Bot API
        bot_kwargs["base_url"] = f"{settings.local_api.url}/bot"
        
    _worker_bot = Bot(token=settings.bot.token, **bot_kwargs)
    return _worker_bot
