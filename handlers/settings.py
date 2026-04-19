from __future__ import annotations

import structlog
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import crud
from database.models import User, UserSettings
from database.session import get_db

log = structlog.get_logger(__name__)
router = Router()


def build_settings_keyboard(stg: UserSettings) -> types.InlineKeyboardMarkup:
    """Build interactive settings keyboard."""
    builder = InlineKeyboardBuilder()

    # Quality row
    qualities = ["360", "480", "720", "1080", "audio"]
    for q in qualities:
        label = f"✅ {q}" if stg.format_quality == q else q
        builder.button(text=label, callback_data=f"set_quality:{q}")

    # Toggles
    builder.button(
        text=f"Compression: {'✅ ON' if stg.compression_enabled else '❌ OFF'}",
        callback_data="toggle:compression_enabled",
    )
    builder.button(
        text=f"Zip Bulk: {'✅ ON' if stg.zip_files else '❌ OFF'}",
        callback_data="toggle:zip_files",
    )
    builder.button(
        text=f"Progress: {'✅ ON' if stg.show_progress else '❌ OFF'}",
        callback_data="toggle:show_progress",
    )

    builder.adjust(5, 1, 1, 1)
    return builder.as_markup()


@router.message(Command("settings"))
async def handle_settings(message: types.Message, db_user: User) -> None:
    """Display user settings."""
    if not db_user.settings:
        await message.reply("❌ Settings not found.")
        return

    await message.reply(
        "⚙️ <b>Your Settings</b>\nConfigure your download preferences below:",
        reply_markup=build_settings_keyboard(db_user.settings),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("set_quality:"))
async def handle_quality_callback(callback: types.CallbackQuery) -> None:
    """Update format quality preference."""
    quality = callback.data.split(":")[1] if callback.data else "720"
    async with get_db() as session:
        user = await crud.upsert_user(
            session, callback.from_user.id, callback.from_user.username
        )
        await crud.update_user_settings(session, user.id, format_quality=quality)
        updated_user = await crud.get_user_by_telegram_id(session, callback.from_user.id)

    if updated_user and updated_user.settings and callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=build_settings_keyboard(updated_user.settings)
        )
    await callback.answer(f"Quality set to {quality}")


@router.callback_query(lambda c: c.data and c.data.startswith("toggle:"))
async def handle_toggle_callback(callback: types.CallbackQuery) -> None:
    """Toggle boolean settings."""
    field = callback.data.split(":")[1] if callback.data else ""
    async with get_db() as session:
        user = await crud.upsert_user(
            session, callback.from_user.id, callback.from_user.username
        )
        if user.settings:
            current_val = getattr(user.settings, field)
            await crud.update_user_settings(session, user.id, **{field: not current_val})
        updated_user = await crud.get_user_by_telegram_id(session, callback.from_user.id)

    if updated_user and updated_user.settings and callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=build_settings_keyboard(updated_user.settings)
        )
    await callback.answer(f"Toggled {field.replace('_', ' ')}")
