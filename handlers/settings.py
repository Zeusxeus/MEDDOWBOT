from __future__ import annotations

import structlog
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import crud
from database.models import User, UserSettings
from database.session import get_db

log = structlog.get_logger(__name__)
router = Router(name="settings")

QUALITIES = {
    "360": "360p",
    "480": "480p",
    "720": "720p",
    "1080": "1080p",
    "audio": "Audio",
    "best": "Best",
}


def get_settings_text(settings: UserSettings) -> str:
    """Generate the settings panel text."""
    compress = "ON" if settings.compression_enabled else "OFF"
    progress = "ON" if settings.show_progress else "OFF"
    up_type = "Video Media" if settings.upload_as_video else "Document"
    
    return (
        "┌─────────────────────────────────────┐\n"
        "│ ⚙️ <b>Your Settings</b>                    │\n"
        "│                                     │\n"
        f"│ 📤 Upload as: <b>{up_type}</b>            │\n"
        f"│ 🗜️ Auto-compress: <b>{compress}</b>               │\n"
        f"│ 📶 Progress updates: <b>{progress}</b>             │\n"
        f"│ 📏 Max file size: <b>{settings.max_file_size}MB</b>              │\n"
        "└─────────────────────────────────────┘"
    )


def build_settings_keyboard(settings: UserSettings) -> types.InlineKeyboardMarkup:
    """Build the main settings keyboard."""
    builder = InlineKeyboardBuilder()
    
    compress_status = "✅ ON" if settings.compression_enabled else "❌ OFF"
    progress_status = "✅ ON" if settings.show_progress else "❌ OFF"
    upload_status = "🎬 Video" if settings.upload_as_video else "📄 File"
    
    builder.button(text=f"📤 Mode: {upload_status}", callback_data="settings:toggle:upload_as_video")
    builder.button(text=f"🗜️ Compress: {compress_status}", callback_data="settings:toggle:compression_enabled")
    builder.button(text=f"📶 Progress: {progress_status}", callback_data="settings:toggle:show_progress")
    builder.button(text="📋 History", callback_data="history:list")
    builder.button(text="❌ Close", callback_data="settings:close")
    
    builder.adjust(1, 2, 2)
    return builder.as_markup()


def build_quality_keyboard(current_quality: str) -> types.InlineKeyboardMarkup:
    """Build the quality sub-menu keyboard with checkmarks."""
    builder = InlineKeyboardBuilder()
    for q_code, q_label in QUALITIES.items():
        text = f"✓ {q_label}" if q_code == current_quality else q_label
        builder.button(text=text, callback_data=f"settings:quality:{q_code}")
    
    builder.button(text="◀ Back", callback_data="settings:main")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


@router.message(Command("settings"))
async def handle_settings(message: Message, db_user: User) -> None:
    """Show comprehensive settings panel."""
    if not db_user.settings:
        return

    await message.reply(
        get_settings_text(db_user.settings),
        reply_markup=build_settings_keyboard(db_user.settings),
    )


@router.callback_query(lambda c: c.data == "settings:main")
async def handle_main_settings(callback: CallbackQuery, db_user: User) -> None:
    """Return to main admin menu."""
    if not db_user.settings or not isinstance(callback.message, Message):
        return

    await callback.message.edit_text(
        get_settings_text(db_user.settings),
        reply_markup=build_settings_keyboard(db_user.settings),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "settings:quality_menu")
async def handle_quality_menu(callback: CallbackQuery, db_user: User) -> None:
    """Show quality sub-menu."""
    if not db_user.settings or not isinstance(callback.message, Message):
        return

    await callback.message.edit_text(
        "📊 <b>Select Download Quality</b>\nChoose your preferred resolution:",
        reply_markup=build_quality_keyboard(db_user.settings.format_quality),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("settings:quality:"))
async def handle_quality_set(callback: CallbackQuery, db_user: User) -> None:
    """Update quality preference."""
    if not callback.data or not isinstance(callback.message, Message):
        return

    quality = callback.data.split(":")[-1]
    async with get_db() as session:
        await crud.update_user_settings(session, db_user.id, format_quality=quality)
        # Refresh user settings from DB for text update
        user = await crud.get_user_by_telegram_id(session, db_user.telegram_id)
        if user and user.settings:
            await callback.message.edit_reply_markup(
                reply_markup=build_quality_keyboard(user.settings.format_quality)
            )

    await callback.answer(f"✅ Quality set to {QUALITIES.get(quality, quality)}")


@router.callback_query(lambda c: c.data and c.data.startswith("settings:toggle:"))
async def handle_toggle(callback: CallbackQuery, db_user: User) -> None:
    """Toggle boolean settings."""
    if not db_user.settings or not callback.data or not isinstance(callback.message, Message):
        return

    field = callback.data.split(":")[-1]
    current_val = getattr(db_user.settings, field)
    new_val = not current_val

    async with get_db() as session:
        await crud.update_user_settings(session, db_user.id, **{field: new_val})
        user = await crud.get_user_by_telegram_id(session, db_user.telegram_id)
        if user and user.settings:
            await callback.message.edit_text(
                get_settings_text(user.settings),
                reply_markup=build_settings_keyboard(user.settings),
            )

    await callback.answer(f"✅ {field.replace('_', ' ').title()} turned {'ON' if new_val else 'OFF'}")


@router.callback_query(lambda c: c.data == "settings:close")
async def handle_close(callback: CallbackQuery) -> None:
    """Close the settings panel."""
    if isinstance(callback.message, Message):
        await callback.message.delete()
    await callback.answer()
