from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from database import crud
from database.models import JobStatus
from database.session import get_db

if TYPE_CHECKING:
    import uuid
    from database.models import User

log = structlog.get_logger(__name__)
router = Router(name="history")

PAGE_SIZE = 5


def time_ago(dt: datetime) -> str:
    """Simple time ago helper."""
    now = datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    
    diff = now - dt
    
    if diff.days > 365:
        return "long ago"
    if diff.days > 30:
        return f"{diff.days // 30} months ago"
    if diff.days > 0:
        return "Yesterday" if diff.days == 1 else f"{diff.days} days ago"
    if diff.seconds > 3600:
        return f"{diff.seconds // 3600} hours ago"
    if diff.seconds > 60:
        return f"{diff.seconds // 60} minutes ago"
    return "just now"


def get_status_emoji(status: JobStatus) -> str:
    """Return emoji for job status."""
    return {
        JobStatus.DONE: "✅",
        JobStatus.FAILED: "❌",
        JobStatus.RUNNING: "⏳",
        JobStatus.PENDING: "⏸️",
        JobStatus.CANCELLED: "🚫",
    }.get(status, "❓")


async def build_history_message(
    session: AsyncSession, user_id: uuid.UUID, page: int = 1
) -> tuple[str, types.InlineKeyboardMarkup]:
    """Build paginated history message and keyboard."""
    total_jobs = await crud.count_user_history(session, user_id)
    total_pages = math.ceil(total_jobs / PAGE_SIZE) or 1
    page = max(1, min(page, total_pages))
    
    jobs = await crud.get_user_history(
        session, user_id, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE
    )

    if not jobs:
        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 Refresh", callback_data="history:page:1")
        return "📋 <b>Your Downloads</b>\n\nYour history is empty.", builder.as_markup()

    lines = [f"📋 <b>Your Downloads (Page {page}/{total_pages})</b>\n"]
    for i, job in enumerate(jobs, 1):
        idx = (page - 1) * PAGE_SIZE + i
        emoji = get_status_emoji(job.status)
        platform = (job.platform or "Unknown").title()
        ago = time_ago(job.created_at)
        
        if job.status == JobStatus.DONE:
            size = f"{job.size_bytes / (1024 * 1024):.1f}MB" if job.size_bytes else "?"
            quality = job.format_requested or "best"
            title = job.filename or "Download completed"
            lines.append(f"{idx}. {emoji} {platform} — {title}\n   📏 {size} | 🎬 {quality} | ⏱ {ago}")
        elif job.status == JobStatus.FAILED:
            reason = (job.error_message or "Unknown error")[:47] + "..." if job.error_message and len(job.error_message) > 50 else job.error_message
            lines.append(f"{idx}. {emoji} {platform} — Failed\n   Reason: {reason}\n   ⏱ {ago}")
        else:
            status_text = "Processing..." if job.status == JobStatus.RUNNING else "Queued..."
            lines.append(f"{idx}. {emoji} {platform} — {status_text}\n   ⏱ {ago}")

    builder = InlineKeyboardBuilder()
    if page > 1:
        builder.button(text="◀ Prev", callback_data=f"history:page:{page - 1}")
    else:
        builder.button(text=" ", callback_data="history:noop")
        
    builder.button(text=f"{page}/{total_pages}", callback_data="history:noop")
    
    if page < total_pages:
        builder.button(text="Next ▶", callback_data=f"history:page:{page + 1}")
    else:
        builder.button(text=" ", callback_data="history:noop")
        
    builder.button(text="🔄 Refresh", callback_data=f"history:page:{page}")
    builder.button(text="🗑️ Clear all", callback_data="history:clear_confirm")
    builder.adjust(3, 2)
    return "\n\n".join(lines), builder.as_markup()


@router.message(Command("history"))
async def handle_history(message: Message, db_user: User) -> None:
    """Display user download history."""
    async with get_db() as session:
        text, kb = await build_history_message(session, db_user.id)
        await message.reply(text, reply_markup=kb)


@router.callback_query(lambda c: c.data and c.data.startswith("history:page:"))
async def handle_history_pagination(callback: CallbackQuery, db_user: User) -> None:
    """Handle history pagination and refresh."""
    if not callback.data:
        return

    page = int(callback.data.split(":")[-1])
    async with get_db() as session:
        text, kb = await build_history_message(session, db_user.id, page=page)

    if isinstance(callback.message, Message):
        if callback.message.text != text or callback.message.reply_markup != kb:
            await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(lambda c: c.data == "history:list")
async def handle_history_list_callback(callback: CallbackQuery, db_user: User) -> None:
    """Switch to history view from settings."""
    async with get_db() as session:
        text, kb = await build_history_message(session, db_user.id)
        if isinstance(callback.message, Message):
            await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(lambda c: c.data == "history:clear_confirm")
async def handle_clear_history_confirm(callback: CallbackQuery) -> None:
    """Confirm history deletion."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Yes, clear it", callback_data="history:clear_exec")
    builder.button(text="❌ No, cancel", callback_data="history:page:1")
    builder.adjust(1, 1)
    
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            "⚠️ <b>Are you sure?</b>\nThis will permanently delete all your download history.",
            reply_markup=builder.as_markup()
        )
    await callback.answer()


@router.callback_query(lambda c: c.data == "history:clear_exec")
async def handle_clear_history_exec(callback: CallbackQuery, db_user: User) -> None:
    """Execute history deletion."""
    async with get_db() as session:
        await crud.clear_user_history(session, db_user.id)
        text, kb = await build_history_message(session, db_user.id)
        if isinstance(callback.message, Message):
            await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer("✅ History cleared")


@router.callback_query(lambda c: c.data == "history:noop")
async def handle_noop(callback: CallbackQuery) -> None:
    """No-op for informational buttons."""
    await callback.answer()
