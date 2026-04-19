from __future__ import annotations

import structlog
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import Message

from database import crud
from database.models import UserSettings
from database.session import get_db

log = structlog.get_logger(__name__)
router = Router()


def build_settings_keyboard(settings: UserSettings) -> types.InlineKeyboardMarkup:
    """Build settings keyboard based on user preferences."""
    quality_options = ["360", "480", "720", "1080", "2160"]
    buttons = []

    # Quality row
    quality_row = []
    for q in quality_options:
        label = f"✅ {q}p" if settings.format_quality == q else f"{q}p"
        quality_row.append(types.InlineKeyboardButton(text=label, callback_data=f"quality:{q}"))
    buttons.append(quality_row)

    # Boolean toggles
    toggles = [
        ("Subtitles", "prefer_subtitles"),
        ("Audio Only", "prefer_audio_only"),
    ]
    for label, field in toggles:
        val = getattr(settings, field)
        status = "✅" if val else "❌"
        buttons.append(
            [
                types.InlineKeyboardButton(
                    text=f"{label}: {status}", callback_data=f"toggle:{field}"
                )
            ]
        )

    return types.InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("settings"))
async def handle_settings(message: types.Message) -> None:
    """Show user settings panel."""
    async with get_db() as session:
        user = await crud.upsert_user(session, message.from_user.id, message.from_user.username)  # type: ignore
        if not user.settings:
            # Should be created by upsert_user
            return

    await message.reply(
        "🛠 <b>Your Settings</b>\nConfigure download preferences below:",
        reply_markup=build_settings_keyboard(user.settings),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("quality:"))
async def handle_quality_callback(callback: types.CallbackQuery) -> None:
    """Update preferred video quality."""
    quality = callback.data.split(":")[1] if callback.data else "720"
    async with get_db() as session:
        user = await crud.upsert_user(session, callback.from_user.id, callback.from_user.username)
        await crud.update_user_settings(session, user.id, format_quality=quality)
        updated_user = await crud.get_user_by_telegram_id(session, callback.from_user.id)

    if updated_user and updated_user.settings and isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(
            reply_markup=build_settings_keyboard(updated_user.settings)
        )
    await callback.answer(f"Quality set to {quality}")


@router.callback_query(lambda c: c.data and c.data.startswith("toggle:"))
async def handle_toggle_callback(callback: types.CallbackQuery) -> None:
    """Toggle boolean settings."""
    field = callback.data.split(":")[1] if callback.data else ""
    async with get_db() as session:
        user = await crud.upsert_user(session, callback.from_user.id, callback.from_user.username)
        if user.settings:
            current_val = getattr(user.settings, field)
            await crud.update_user_settings(session, user.id, **{field: not current_val})
        updated_user = await crud.get_user_by_telegram_id(session, callback.from_user.id)

    if updated_user and updated_user.settings and isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(
            reply_markup=build_settings_keyboard(updated_user.settings)
        )
    await callback.answer(f"Toggled {field.replace('_', ' ')}")
