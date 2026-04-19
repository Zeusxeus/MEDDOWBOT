from __future__ import annotations

import asyncpraw  # type: ignore
import structlog
from aiogram import Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from config.settings import settings
from database import crud
from database.session import get_db
from workers.preflight import preflight_task

log = structlog.get_logger(__name__)
router = Router()


class RedditBulk(StatesGroup):
    waiting_for_subreddit = State()
    waiting_for_count = State()
    waiting_for_sort = State()


@router.message(Command("reddit"))
async def handle_reddit_start(message: types.Message, state: FSMContext) -> None:
    """Start subreddit bulk download FSM."""
    await state.set_state(RedditBulk.waiting_for_subreddit)
    await message.reply("🤖 Enter subreddit name (e.g., 'memes'):")


@router.message(StateFilter(RedditBulk.waiting_for_subreddit))
async def process_subreddit(message: types.Message, state: FSMContext) -> None:
    """Store subreddit and ask for count."""
    await state.update_data(subreddit=message.text)
    await state.set_state(RedditBulk.waiting_for_count)
    await message.reply("How many posts? (default 10, max 50):")


@router.message(StateFilter(RedditBulk.waiting_for_count))
async def process_count(message: types.Message, state: FSMContext) -> None:
    """Store count and ask for sort."""
    try:
        count = int(message.text) if message.text else 10
    except ValueError:
        count = 10
    await state.update_data(count=min(max(count, 1), 50))

    builder = ReplyKeyboardBuilder()
    for s in ["hot", "new", "top", "rising"]:
        builder.button(text=s)

    await state.set_state(RedditBulk.waiting_for_sort)
    await message.reply(
        "Select sort order:",
        reply_markup=builder.as_markup(resize_keyboard=True, one_time_keyboard=True),
    )


@router.message(StateFilter(RedditBulk.waiting_for_sort))
async def process_sort(message: types.Message, state: FSMContext) -> types.Message | None:
    """Fetch posts and enqueue tasks."""
    data = await state.get_data()
    sub_name = data["subreddit"]
    count = data["count"]
    sort = message.text or "hot"

    if not settings.reddit.client_id or not settings.reddit.client_secret:
        await state.clear()
        return await message.reply("❌ Reddit API not configured by admin.")

    sent = await message.reply(f"🔍 Fetching {count} posts from r/{sub_name} ({sort})...")

    reddit = asyncpraw.Reddit(
        client_id=settings.reddit.client_id,
        client_secret=settings.reddit.client_secret,
        user_agent=settings.reddit.user_agent,
    )

    try:
        subreddit = await reddit.subreddit(sub_name)
        func = getattr(subreddit, sort)
        posts = []
        async for post in func(limit=count):
            if not post.is_self and post.url:
                posts.append(post.url)

        if not posts:
            return await sent.edit_text("❌ No media posts found.")

        await sent.edit_text(f"🚀 Found {len(posts)} media posts. Queuing...")

        async with get_db() as session:
            user = await crud.upsert_user(
                session, message.from_user.id, message.from_user.username  # type: ignore
            )
            if not user.settings:
                return await message.reply("❌ User settings not found.")

            for url in posts:
                job = await crud.create_download_job(
                    session, user.id, url, user.settings.format_quality
                )
                await preflight_task.kiq(
                    url=url,
                    user_id_str=str(user.id),
                    job_id_str=str(job.id),
                    format_quality=user.settings.format_quality,
                    chat_id=message.chat.id,
                    message_id=sent.message_id,
                )

        return await message.reply(f"✅ Enqueued {len(posts)} downloads.")
    except Exception as e:
        log.exception("reddit_bulk_failed")
        return await sent.edit_text(f"❌ Failed to fetch from Reddit: {e}")
    finally:
        await reddit.close()
        await state.clear()
