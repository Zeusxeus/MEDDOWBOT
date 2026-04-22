from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from database import crud
from database.models import User
from database.session import get_db
from handlers.admin_states import AdminAction, AdminStates
from utils import admin as admin_utils
from utils.cookies import cookie_manager
from utils.system import get_system_metrics

if TYPE_CHECKING:
    pass

log = structlog.get_logger(__name__)
router = Router()


# ─────────────────────────────────────────────
# MAIN DASHBOARD
# ─────────────────────────────────────────────


@router.message(Command("admin"))
async def handle_admin_command(message: types.Message, db_user: User | None = None) -> None:
    """Handle /admin command."""
    if not db_user or not db_user.is_admin:
        return
    text = "🔐 <b>Admin Dashboard</b>\n━━━━━━━━━━━━━━━━━━━━━\nSelect a section below:"
    await message.answer(text, reply_markup=admin_utils.get_main_menu_kb(), parse_mode="HTML")


@router.callback_query(AdminAction.filter(F.action == "main"))
async def handle_main_menu(query: types.CallbackQuery, db_user: User | None = None) -> None:
    """Return to main admin menu."""
    if not db_user or not db_user.is_admin or not isinstance(query.message, types.Message):
        return
    text = "🔐 <b>Admin Dashboard</b>\n━━━━━━━━━━━━━━━━━━━━━\nSelect a section below:"
    await query.message.edit_text(text, reply_markup=admin_utils.get_main_menu_kb(), parse_mode="HTML")


# ─────────────────────────────────────────────
# STATISTICS
# ─────────────────────────────────────────────


@router.callback_query(AdminAction.filter(F.action == "stats"))
async def handle_stats(query: types.CallbackQuery, db_user: User | None = None) -> None:
    """Show admin stats."""
    if not db_user or not db_user.is_admin or not isinstance(query.message, types.Message):
        return
    text = await admin_utils.get_admin_stats_text()
    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="◀ Back", callback_data=AdminAction(action="main").pack()
                )
            ]
        ]
    )
    await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


# ─────────────────────────────────────────────
# USER MANAGEMENT
# ─────────────────────────────────────────────


@router.callback_query(AdminAction.filter(F.action == "users"))
async def handle_users_list(
    query: types.CallbackQuery, callback_data: AdminAction, db_user: User | None = None
) -> None:
    """Show users list."""
    if not db_user or not db_user.is_admin or not isinstance(query.message, types.Message):
        return
    text, kb = await admin_utils.get_users_list_data(page=callback_data.page)
    await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(AdminAction.filter(F.action == "user_info"))
async def handle_user_info(
    query: types.CallbackQuery, callback_data: AdminAction, db_user: User | None = None
) -> None:
    """Show user info."""
    if not db_user or not db_user.is_admin or not isinstance(query.message, types.Message):
        return
    if callback_data.user_id is None:
        return
    text, kb = await admin_utils.get_user_info_data(callback_data.user_id)
    await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(AdminAction.filter(F.action == "ban"))
async def handle_ban(
    query: types.CallbackQuery, callback_data: AdminAction, db_user: User | None = None
) -> None:
    """Ban user."""
    if not db_user or not db_user.is_admin or not isinstance(query.message, types.Message):
        return
    if callback_data.user_id is None:
        return
    async with get_db() as session:
        await crud.set_user_ban(session, callback_data.user_id, True)
    text, kb = await admin_utils.get_user_info_data(callback_data.user_id)
    await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(AdminAction.filter(F.action == "unban"))
async def handle_unban(
    query: types.CallbackQuery, callback_data: AdminAction, db_user: User | None = None
) -> None:
    """Unban user."""
    if not db_user or not db_user.is_admin or not isinstance(query.message, types.Message):
        return
    if callback_data.user_id is None:
        return
    async with get_db() as session:
        await crud.set_user_ban(session, callback_data.user_id, False)
    text, kb = await admin_utils.get_user_info_data(callback_data.user_id)
    await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


# ─────────────────────────────────────────────
# QUEUE
# ─────────────────────────────────────────────


@router.callback_query(AdminAction.filter(F.action == "queue"))
async def handle_queue(query: types.CallbackQuery, db_user: User | None = None) -> None:
    """Show queue depth."""
    if not db_user or not db_user.is_admin or not isinstance(query.message, types.Message):
        return
    text = await admin_utils.get_queue_text()
    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="◀ Back", callback_data=AdminAction(action="main").pack()
                )
            ]
        ]
    )
    await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


# ─────────────────────────────────────────────
# PROXIES
# ─────────────────────────────────────────────


@router.callback_query(AdminAction.filter(F.action == "proxies"))
async def handle_proxies(query: types.CallbackQuery, db_user: User | None = None) -> None:
    """Show proxies list."""
    if not db_user or not db_user.is_admin or not isinstance(query.message, types.Message):
        return
    text = await admin_utils.get_proxies_text()
    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="➕ Add Proxy", callback_data=AdminAction(action="proxy_add").pack()
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="◀ Back", callback_data=AdminAction(action="main").pack()
                )
            ],
        ]
    )
    await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(AdminAction.filter(F.action == "proxy_add"))
async def handle_proxy_add_start(
    query: types.CallbackQuery, state: FSMContext, db_user: User | None = None
) -> None:
    """Start proxy add flow."""
    if not db_user or not db_user.is_admin or not isinstance(query.message, types.Message):
        return
    await state.set_state(AdminStates.waiting_for_proxy)
    await query.message.edit_text(
        "➕ Send proxy: <code>host:port:user:pass</code>", parse_mode="HTML"
    )


@router.message(AdminStates.waiting_for_proxy)
async def handle_proxy_add_finish(
    message: types.Message, state: FSMContext, db_user: User | None = None
) -> None:
    """Finish proxy add flow."""
    if not db_user or not db_user.is_admin:
        return
    try:
        from database.models import Proxy

        proxy = Proxy.from_string(message.text or "")
        proxy.added_by_user_id = db_user.id
        async with get_db() as session:
            await crud.add_proxy(session, proxy)
        await message.answer("✅ Proxy added.")
    except Exception as e:
        await message.answer(f"❌ Error: {e}")
    finally:
        await state.clear()


# ─────────────────────────────────────────────
# COOKIES
# ─────────────────────────────────────────────


@router.callback_query(AdminAction.filter(F.action == "cookies"))
async def handle_cookies(query: types.CallbackQuery, db_user: User | None = None) -> None:
    """Show cookies management."""
    if not db_user or not db_user.is_admin or not isinstance(query.message, types.Message):
        return
    text = await admin_utils.get_cookies_text()
    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="📤 Upload YouTube",
                    callback_data=AdminAction(action="cookie_up", data="youtube").pack(),
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="◀ Back", callback_data=AdminAction(action="main").pack()
                )
            ],
        ]
    )
    await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(AdminAction.filter(F.action == "cookie_up"))
async def handle_cookie_up_start(
    query: types.CallbackQuery,
    callback_data: AdminAction,
    state: FSMContext,
    db_user: User | None = None,
) -> None:
    """Start cookie upload flow."""
    if not db_user or not db_user.is_admin or not isinstance(query.message, types.Message):
        return
    await state.set_state(AdminStates.waiting_for_cookie_file)
    await state.update_data(platform=callback_data.data)
    await query.message.edit_text(
        f"📤 Upload .txt cookie file for <b>{callback_data.data}</b>", parse_mode="HTML"
    )


@router.message(AdminStates.waiting_for_cookie_file, F.document)
async def handle_cookie_up_finish(
    message: types.Message, state: FSMContext, db_user: User | None = None
) -> None:
    """Finish cookie upload flow."""
    if not db_user or not db_user.is_admin or not message.document:
        return
    data = await state.get_data()
    if message.bot:
        file = await message.bot.get_file(message.document.file_id)
        content = await message.bot.download_file(file.file_path or "")
        if content:
            ok, msg = await cookie_manager.save_cookie_file(
                data["platform"], content.read(), db_user.id
            )
            await message.answer(f"Result: {msg}")
    await state.clear()


# ─────────────────────────────────────────────
# SYSTEM
# ─────────────────────────────────────────────


@router.callback_query(AdminAction.filter(F.action == "system"))
async def handle_system(query: types.CallbackQuery, db_user: User | None = None) -> None:
    """Show system metrics."""
    if not db_user or not db_user.is_admin or not isinstance(query.message, types.Message):
        return
    m = await get_system_metrics()
    text = (
        f"⚙️ <b>System</b>\nUptime: {m.uptime}\nRedis: {m.redis_usage}\nDB: {m.db_usage}\n"
        f"Disk: {m.disk_used}/{m.disk_total} ({m.disk_percent}%)\nQueue: {m.queue_depth}"
    )
    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="◀ Back", callback_data=AdminAction(action="main").pack()
                )
            ]
        ]
    )
    await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


# ─────────────────────────────────────────────
# BROADCAST
# ─────────────────────────────────────────────


@router.callback_query(AdminAction.filter(F.action == "broadcast"))
async def handle_broadcast_start(
    query: types.CallbackQuery, state: FSMContext, db_user: User | None = None
) -> None:
    """Start broadcast flow."""
    if not db_user or not db_user.is_admin or not isinstance(query.message, types.Message):
        return
    await state.set_state(AdminStates.waiting_for_broadcast)
    await query.message.edit_text("📢 Send the message for broadcast:")


@router.message(AdminStates.waiting_for_broadcast)
async def handle_broadcast_confirm(
    message: types.Message, state: FSMContext, db_user: User | None = None
) -> None:
    """Confirm broadcast message."""
    if not db_user or not db_user.is_admin:
        return
    await state.update_data(msg=message.text)
    await state.set_state(AdminStates.confirm_broadcast)
    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="✅ Confirm Send",
                    callback_data=AdminAction(action="broadcast_send").pack(),
                )
            ]
        ]
    )
    await message.answer(f"Confirm broadcast:\n\n{message.text}", reply_markup=kb)


@router.callback_query(AdminAction.filter(F.action == "broadcast_send"))
async def handle_broadcast_send(
    query: types.CallbackQuery, state: FSMContext, db_user: User | None = None
) -> None:
    """Execute broadcast."""
    if not db_user or not db_user.is_admin or not isinstance(query.message, types.Message):
        return
    data = await state.get_data()
    if query.bot:
        asyncio.create_task(admin_utils.do_broadcast(query.bot, data["msg"]))  # Background task
    await query.message.edit_text("🚀 Broadcast started in background.")
    await state.clear()
