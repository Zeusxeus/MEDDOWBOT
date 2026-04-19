from __future__ import annotations

from datetime import UTC, datetime

import structlog
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import crud
from database.models import JobStatus
from database.session import get_db

log = structlog.get_logger(__name__)
router = Router()

PAGE_SIZE = 5


def time_ago(dt: datetime) -> str:
    """Simple time ago helper."""
    diff = datetime.now(UTC) - dt.replace(tzinfo=UTC)
    if diff.days > 0:
        return f"{diff.days}d ago"
    if diff.seconds > 3600:
        return f"{diff.seconds // 3600}h ago"
    if diff.seconds > 60:
        return f"{diff.seconds // 60}m ago"
    return "just now"


def get_status_emoji(status: JobStatus) -> str:
    """Return emoji for job status."""
    return {
        JobStatus.DONE: "✅",
        JobStatus.FAILED: "❌",
        JobStatus.RUNNING: "⏳",
        JobStatus.PENDING: "🕒",
        JobStatus.CANCELLED: "🚫",
    }.get(status, "❓")


async def build_history_message(session, user_id, page: int = 0) -> tuple[str, types.InlineKeyboardMarkup]:
    """Build paginated history message and keyboard."""
    jobs = await crud.get_user_history(session, user_id, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    
    if not jobs:
        return "📜 Your history is empty.", InlineKeyboardBuilder().as_markup()

    lines = ["📜 <b>Your Recent Downloads</b>\n"]
    for job in jobs:
        size = f"{job.size_bytes / (1024 * 1024):.1f}MB" if job.size_bytes else "?"
        platform = job.platform or "unknown"
        emoji = get_status_emoji(job.status)
        ago = time_ago(job.created_at)
        lines.append(
            f"{emoji} <code>{platform}</code> | {job.format_requested} | {size}\n"
            f"└ <i>{ago}</i> — <code>{str(job.id)[:8]}</code>"
        )

    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="⬅️ Prev", callback_data=f"history_page:{page - 1}")
    if len(jobs) == PAGE_SIZE:
        builder.button(text="Next ➡️", callback_data=f"history_page:{page + 1}")
    
    return "\n\n".join(lines), builder.as_markup()


@router.message(Command("history"))
async def handle_history(message: types.Message) -> None:
    """Display user download history."""
    async with get_db() as session:
        user = await crud.upsert_user(session, message.from_user.id, message.from_user.username)  # type: ignore
        text, kb = await build_history_message(session, user.id)
        await message.reply(text, reply_markup=kb)


@router.callback_query(lambda c: c.data and c.data.startswith("history_page:"))
async def handle_history_pagination(callback: types.CallbackQuery) -> None:
    """Handle history pagination."""
    page = int(callback.data.split(":")[1])  # type: ignore
    async with get_db() as session:
        user = await crud.upsert_user(session, callback.from_user.id, callback.from_user.username)
        text, kb = await build_history_message(session, user.id, page=page)
        
    await callback.message.edit_text(text, reply_markup=kb)  # type: ignore
    await callback.answer()
