from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from cache.rate_limiter import check_rate_limit
from database import crud
from database.session import get_db

if TYPE_CHECKING:
    from database.models import User

URL_PATTERN = re.compile(r"https?://\S+")


class RateLimitMiddleware(BaseMiddleware):
    """
    Middleware to enforce rate limits on download requests.
    Bypassed for admins.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Any],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.text or not event.from_user:
            return await handler(event, data)

        db_user: User | None = data.get("db_user")
        if not db_user:
            return await handler(event, data)

        # Bypass rate limit for admins
        if db_user.is_admin:
            return await handler(event, data)

        text = event.text.strip()
        is_download_command = text.startswith("/download")
        is_url_message = bool(URL_PATTERN.match(text))

        if is_download_command or is_url_message:
            allowed, reset_in = await check_rate_limit(
                user_id=event.from_user.id,
                override_limit=db_user.rate_limit_override,
            )

            if not allowed:
                await event.answer(f"⚠️ Rate limit exceeded. Try again in {reset_in} seconds.")

                # Log to DB for analytics
                async with get_db() as session:
                    await crud.log_rate_limit(session, db_user.id)

                return

        return await handler(event, data)
