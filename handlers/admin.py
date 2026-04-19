from __future__ import annotations

import structlog
from aiogram import F, Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import func, select

from config.settings import settings
from database import crud
from database.models import CookieFile, DownloadJob, JobStatus, Proxy, User
from database.session import get_db

log = structlog.get_logger(__name__)
router = Router()


class AdminFilter:
    """Filter to only allow admins (from DB or config)."""

    async def __call__(self, event: types.TelegramObject, db_user: User) -> bool:
        return db_user.is_admin or db_user.telegram_id in settings.bot.admin_ids


class CookieUpload(StatesGroup):
    waiting_for_platform = State()
    waiting_for_file = State()


# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────


@router.message(Command("admin"), AdminFilter())
async def handle_admin_dashboard(message: types.Message, db_user: User) -> None:
    """Show admin dashboard with stats."""
    async with get_db() as session:
        users = await session.scalar(select(func.count(User.id))) or 0
        jobs = await session.scalar(select(func.count(DownloadJob.id))) or 0
        done = (
            await session.scalar(
                select(func.count(DownloadJob.id)).where(DownloadJob.status == JobStatus.DONE)
            )
            or 0
        )
        rate = (done / jobs * 100) if jobs else 0.0

    await message.reply(
        f"🛠 <b>Admin Dashboard</b>\n\n"
        f"👥 Users: {users}\n"
        f"📦 Jobs: {jobs}\n"
        f"✅ Success: {rate:.1f}%\n\n"
        f"Commands:\n"
        f"/admin_proxies — List/Add proxies\n"
        f"/admin_cookies — Manage cookies\n"
        f"/ban <code>telegram_id</code> — Ban user"
    )


# ─────────────────────────────────────────────
# PROXY MGMT
# ─────────────────────────────────────────────


@router.message(Command("admin_proxies"), AdminFilter())
async def handle_admin_proxies(message: types.Message, db_user: User) -> None:
    """List all proxies."""
    async with get_db() as session:
        proxies = await crud.get_all_proxies(session)

    if not proxies:
        await message.reply("No proxies configured. Use <code>/proxy_add host:port:u:p</code>")
        return

    lines = ["🌐 <b>Proxy Pool</b>"]
    for p in proxies:
        lines.append(f"• <code>{p.display_str}</code> — {p.status.value}")
    await message.reply("\n".join(lines))


@router.message(Command("proxy_add"), AdminFilter())
async def handle_proxy_add(message: types.Message, db_user: User) -> None:
    """Add a new proxy. Format: host:port:username:password"""
    if not message.text or len(message.text.split()) < 2:
        await message.reply("Usage: <code>/proxy_add host:port:user:pass</code>")
        return

    proxy_str = message.text.split(None, 1)[1]
    try:
        proxy = Proxy.from_string(proxy_str)
        async with get_db() as session:
            await crud.add_proxy(session, proxy)
        await message.reply("✅ Proxy added.")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")


# ─────────────────────────────────────────────
# COOKIE MGMT
# ─────────────────────────────────────────────


@router.message(Command("admin_cookies"), AdminFilter())
async def handle_admin_cookies(message: types.Message, state: FSMContext, db_user: User) -> None:
    """Start cookie upload process."""
    await state.set_state(CookieUpload.waiting_for_platform)
    await message.reply("🍪 Enter platform name (e.g., youtube, instagram):")


@router.message(StateFilter(CookieUpload.waiting_for_platform))
async def process_cookie_platform(message: types.Message, state: FSMContext) -> None:
    """Store platform and ask for file."""
    await state.update_data(platform=message.text.lower() if message.text else "unknown")
    await state.set_state(CookieUpload.waiting_for_file)
    await message.reply(f"Upload .txt cookie file for <b>{message.text}</b>:")


@router.message(StateFilter(CookieUpload.waiting_for_file), F.document)
async def process_cookie_file(message: types.Message, state: FSMContext) -> None:
    """Save cookie file and update DB."""
    data = await state.get_data()
    platform = data["platform"]
    doc = message.document

    if not doc or not doc.file_name or not doc.file_name.endswith(".txt"):
        await message.reply("❌ Please upload a .txt file.")
        return

    dest = settings.cookies.path / platform
    dest.mkdir(parents=True, exist_ok=True)
    file_path = dest / doc.file_name

    bot = message.bot
    if bot:
        await bot.download(doc, destination=str(file_path))

    async with get_db() as session:
        await crud.deactivate_all_cookies(session, platform)
        db_user = await crud.get_user_by_telegram_id(session, message.from_user.id)  # type: ignore
        cookie = CookieFile(
            platform=platform,
            filename=doc.file_name,
            is_active=True,
            uploaded_by_user_id=db_user.id if db_user else None,
        )
        session.add(cookie)

    await state.clear()
    await message.reply(f"✅ Cookies for {platform} updated.")


# ─────────────────────────────────────────────
# USER MGMT
# ─────────────────────────────────────────────


@router.message(Command("ban"), AdminFilter())
async def handle_ban(message: types.Message, db_user: User) -> None:
    """Ban a user by Telegram ID."""
    if not message.text or len(message.text.split()) < 2:
        await message.reply("Usage: <code>/ban 12345678</code>")
        return

    try:
        tid = int(message.text.split()[1])
        async with get_db() as session:
            success = await crud.set_user_ban(session, tid, True)
        await message.reply("✅ User banned." if success else "❌ User not found.")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")
