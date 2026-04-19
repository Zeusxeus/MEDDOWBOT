from __future__ import annotations

from typing import Any, Callable

import structlog
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

log = structlog.get_logger(__name__)


class LoggingMiddleware(BaseMiddleware):
    """
    Middleware to bind user context to structlog and log incoming updates.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Any],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        user_id = user.id if user else None
        username = user.username if user else None

        structlog.contextvars.bind_contextvars(
            user_id=user_id,
            username=username,
            update_id=getattr(event, "update_id", None),
        )

        try:
            return await handler(event, data)
        finally:
            structlog.contextvars.clear_contextvars()
