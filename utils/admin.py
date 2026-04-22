from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import structlog
from aiogram import Bot, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select, desc

from database import crud
from database.models import DownloadJob, JobStatus, User, Proxy, CookieFile
from database.session import get_db
from utils.system import format_size
from handlers.admin_states import AdminAction

log = structlog.get_logger(__name__)


async def get_admin_stats_text() -> str:
    """Gather and format bot statistics."""
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with get_db() as session:
        total_users = await session.scalar(select(func.count(User.id))) or 0
        active_today = await session.scalar(
            select(func.count(User.id)).where(User.last_seen_at >= today_start)
        ) or 0
        total_jobs = await session.scalar(select(func.count(DownloadJob.id))) or 0
        successful = await session.scalar(
            select(func.count(DownloadJob.id)).where(DownloadJob.status == JobStatus.DONE)
        ) or 0
        failed = await session.scalar(
            select(func.count(DownloadJob.id)).where(DownloadJob.status == JobStatus.FAILED)
        ) or 0
        total_bytes = await session.scalar(select(func.sum(User.total_bytes_served))) or 0

    success_pct = (successful / total_jobs * 100) if total_jobs else 0
    
    return (
        "📊 <b>Bot Statistics</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 <b>Users:</b> {total_users} ({active_today} active today)\n"
        f"📥 <b>Jobs:</b> {total_jobs} total\n"
        f"✅ <b>Success:</b> {successful} ({success_pct:.1f}%)\n"
        f"❌ <b>Failed:</b> {failed}\n"
        f"💾 <b>Data:</b> {format_size(total_bytes or 0)} served\n"
    )


async def get_users_list_data(page: int, per_page: int = 10) -> tuple[str, types.InlineKeyboardMarkup]:
    """Get paginated users list."""
    offset = (page - 1) * per_page
    async with get_db() as session:
        total_users = await session.scalar(select(func.count(User.id))) or 0
        stmt = select(User).order_by(desc(User.last_seen_at)).limit(per_page).offset(offset)
        users = (await session.execute(stmt)).scalars().all()

    total_pages = (total_users + per_page - 1) // per_page
    text = f"👥 <b>Users (Page {page}/{total_pages}, Total: {total_users})</b>\n\n"
    
    builder = InlineKeyboardBuilder()
    
    for u in users:
        status = "🔴" if u.is_banned else "🟢"
        username = f"@{u.username}" if u.username else f"ID:{u.telegram_id}"
        text += f"{status} {username} (<code>{u.telegram_id}</code>)\n"
        builder.button(text=f"👤 {username}", callback_data=AdminAction(action="user_info", user_id=u.telegram_id))

    # Pagination
    nav_buttons = []
    if page > 1:
        nav_buttons.append(types.InlineKeyboardButton(text="⬅️", callback_data=AdminAction(action="users", page=page-1).pack()))
    if page < total_pages:
        nav_buttons.append(types.InlineKeyboardButton(text="➡️", callback_data=AdminAction(action="users", page=page+1).pack()))
    
    if nav_buttons:
        builder.row(*nav_buttons)
        
    builder.row(types.InlineKeyboardButton(text="◀ Back", callback_data=AdminAction(action="main").pack()))
    builder.adjust(1)
    return text, builder.as_markup()


async def get_user_info_data(telegram_id: int) -> tuple[str, types.InlineKeyboardMarkup]:
    """Get detailed user info and management buttons."""
    async with get_db() as session:
        u = await crud.get_user_by_telegram_id(session, telegram_id)
        
    if not u:
        return "❌ User not found.", InlineKeyboardBuilder().button(text="◀ Back", callback_data=AdminAction(action="users")).as_markup()

    text = (
        f"👤 <b>User Info</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"ID: <code>{u.telegram_id}</code>\n"
        f"Username: @{u.username or 'None'}\n"
        f"Status: {'🔴 BANNED' if u.is_banned else '🟢 Active'}\n"
        f"Total downloads: {u.total_downloads}\n"
        f"Total data: {format_size(u.total_bytes_served)}\n"
        f"Last seen: {u.last_seen_at.strftime('%Y-%m-%d %H:%M') if u.last_seen_at else 'never'}\n"
    )
    
    builder = InlineKeyboardBuilder()
    if u.is_banned:
        builder.button(text="✅ Unban", callback_data=AdminAction(action="unban", user_id=u.telegram_id))
    else:
        builder.button(text="🚫 Ban", callback_data=AdminAction(action="ban", user_id=u.telegram_id))
        
    builder.button(text="📋 View history", callback_data=AdminAction(action="user_history", user_id=u.telegram_id))
    builder.button(text="◀ Back to users", callback_data=AdminAction(action="users"))
    builder.adjust(1)
    return text, builder.as_markup()


async def get_queue_text() -> str:
    """Gather and format queue status."""
    async with get_db() as session:
        active = (await session.execute(
            select(DownloadJob).where(DownloadJob.status == JobStatus.RUNNING).limit(5)
        )).scalars().all()
        pending = (await session.execute(
            select(DownloadJob).where(DownloadJob.status == JobStatus.PENDING).limit(5)
        )).scalars().all()

    text = "📥 <b>Job Queue</b>\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    text += "<b>Active:</b>\n" + ("\n".join([f"🔄 {j.platform} - <code>{str(j.id)[:8]}</code>" for j in active]) or "  <i>None</i>")
    text += "\n\n<b>Pending:</b>\n" + ("\n".join([f"⏳ <code>{str(j.id)[:8]}</code>" for j in pending]) or "  <i>None</i>")
    return text


async def get_proxies_text() -> str:
    """Gather and format proxy status."""
    async with get_db() as session:
        proxies = (await session.execute(select(Proxy))).scalars().all()
    
    text = "🌐 <b>Proxies</b>\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    if not proxies:
        text += "<i>No proxies configured.</i>"
    for p in proxies:
        status = "🟢" if p.status == "active" else "🔴"
        text += f"{status} <code>{p.host}</code> ({p.total_uses} uses)\n"
    return text


async def get_cookies_text() -> str:
    """Gather and format cookie status."""
    async with get_db() as session:
        cookies = (await session.execute(select(CookieFile))).scalars().all()
    
    text = "🍪 <b>Cookies</b>\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    if not cookies:
        text += "<i>No cookies uploaded.</i>"
    for c in cookies:
        status = "✅" if c.is_valid else "❌"
        text += f"{status} <b>{c.platform}</b> ({c.filename})\n"
    return text


def get_main_menu_kb() -> types.InlineKeyboardMarkup:
    """Main admin menu keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Stats", callback_data=AdminAction(action="stats"))
    builder.button(text="👥 Users", callback_data=AdminAction(action="users"))
    builder.button(text="📥 Queue", callback_data=AdminAction(action="queue"))
    builder.button(text="🌐 Proxies", callback_data=AdminAction(action="proxies"))
    builder.button(text="🍪 Cookies", callback_data=AdminAction(action="cookies"))
    builder.button(text="📢 Broadcast", callback_data=AdminAction(action="broadcast"))
    builder.button(text="⚙️ System", callback_data=AdminAction(action="system"))
    builder.adjust(2)
    return builder.as_markup()


async def add_proxy_from_string(proxy_str: str, user_id: uuid.UUID) -> str:
    """Parse and add proxy to database."""
    try:
        proxy = Proxy.from_string(proxy_str)
        proxy.added_by_user_id = user_id
        async with get_db() as session:
            await crud.add_proxy(session, proxy)
        return "✅ Proxy added successfully."
    except Exception as e:
        return f"❌ Error adding proxy: {e}"


async def do_broadcast(bot: Bot, text: str) -> None:
    """Heavy lifting for broadcast."""
    async with get_db() as session:
        user_ids = (await session.execute(select(User.telegram_id))).scalars().all()
    sent = 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            continue
    log.info("broadcast_complete", total=len(user_ids), sent=sent)
