from __future__ import annotations

import structlog
from aiogram import Bot

from config.settings import settings

log = structlog.get_logger(__name__)


async def notify_admins(bot: Bot, message: str) -> None:
    """
    Send a notification to all admins defined in settings.
    
    Args:
        bot: The Bot instance to use for sending.
        message: The message to send.
    """
    if not settings.bot.admin_ids:
        log.warning("no_admins_configured_for_notification")
        return

    for admin_id in settings.bot.admin_ids:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=f"🔔 <b>Admin Notification</b>\n\n{message}",
                parse_mode="HTML",
            )
        except Exception as e:
            log.error("failed_to_notify_admin", admin_id=admin_id, error=str(e))
