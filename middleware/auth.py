from __future__ import annotations

from typing import Any, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from database import crud
from database.session import get_db


class AuthMiddleware(BaseMiddleware):
    """
    Middleware to authenticate users and inject them into the handler data.
    Updates user info on every interaction.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Any],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if not user or user.is_bot:
            return await handler(event, data)

        async with get_db() as session:
            db_user = await crud.upsert_user(
                session=session,
                telegram_id=user.id,
                username=user.username,
                first_name=user.first_name,
            )

            if db_user.is_banned:
                return  # Silent drop for banned users

            # Inject into data for handlers and subsequent middlewares
            data["db_user"] = db_user
            data["user_settings"] = db_user.settings

        return await handler(event, data)
