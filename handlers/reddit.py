from __future__ import annotations

import httpx
import structlog
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config.settings import settings
from database import crud
from database.models import User
from database.session import get_db
from workers.preflight import preflight_task

log = structlog.get_logger(__name__)
router = Router(name="reddit")


class RedditBulk(StatesGroup):
    waiting_for_subreddit = State()
    waiting_for_count = State()
    waiting_for_sort = State()


async def _fetch_reddit_posts(subreddit: str, count: int, sort: str) -> list[str]:
    """Fetch video URLs from subreddit using Reddit's public JSON API."""
    url = f"https://www.reddit.com/r/{subreddit}/{sort}.json"
    params = {"limit": min(count * 3, 100)}
    headers = {"User-Agent": settings.reddit.user_agent}
    
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(url, params=params, headers=headers)
        if response.status_code == 404:
            raise ValueError(f"Subreddit r/{subreddit} not found or private")
        if response.status_code == 403:
            raise ValueError(f"Subreddit r/{subreddit} is private or quarantined")
        response.raise_for_status()
        data = response.json()
    
    posts = data.get("data", {}).get("children", [])
    video_urls = []
    for post in posts:
        pd = post.get("data", {})
        if pd.get("stickied"):
            continue
        
        url_from_pd = pd.get("url", "")
        if pd.get("is_video") and pd.get("media"):
            video_urls.append(f"https://www.reddit.com{pd['permalink']}")
        elif any(domain in url_from_pd for domain in [
            "youtube.com", "youtu.be", "v.redd.it", "streamable.com",
            "gfycat.com", "redgifs.com", "imgur.com", "i.imgur.com",
            "giphy.com", "twitter.com", "x.com", "instagram.com",
            "tiktok.com", "clips.twitch.tv"
        ]):
            video_urls.append(url_from_pd)
        
        if len(video_urls) >= count:
            break
    return video_urls[:count]


@router.message(Command("reddit"))
async def handle_reddit_start(message: types.Message, state: FSMContext) -> None:
    """Start subreddit bulk download FSM."""
    if not settings.reddit.enabled:
        await message.reply("❌ Reddit feature is not enabled.")
        return

    await state.set_state(RedditBulk.waiting_for_subreddit)
    await message.reply("🤖 Enter subreddit name (without r/):")


@router.message(RedditBulk.waiting_for_subreddit)
async def process_subreddit(message: types.Message, state: FSMContext) -> None:
    """Store subreddit and ask for count."""
    sub_name = (message.text or "").strip().lower()
    if sub_name.startswith("r/"):
        sub_name = sub_name[2:]
        
    await state.update_data(subreddit=sub_name)
    await state.set_state(RedditBulk.waiting_for_count)
    await message.reply("🔢 How many posts? (1-50, default 10):")


@router.message(RedditBulk.waiting_for_count)
async def process_count(message: types.Message, state: FSMContext) -> None:
    """Store count and ask for sort."""
    try:
        count = int(message.text) if message.text else 10
    except ValueError:
        count = 10
        
    count = min(max(count, 1), settings.reddit.max_posts_per_request)
    await state.update_data(count=count)

    builder = InlineKeyboardBuilder()
    for s in ["hot", "new", "top", "rising"]:
        builder.button(text=s.capitalize(), callback_data=f"reddit_sort:{s}")
    builder.adjust(2)

    await state.set_state(RedditBulk.waiting_for_sort)
    await message.reply("📂 Sort by:", reply_markup=builder.as_markup())


@router.callback_query(RedditBulk.waiting_for_sort)
async def process_sort(callback: types.CallbackQuery, state: FSMContext, db_user: User) -> None:
    """Fetch posts and enqueue tasks."""
    if not callback.data or not callback.data.startswith("reddit_sort:") or not isinstance(callback.message, types.Message):
        return

    sort = callback.data.split(":")[1]
    data = await state.get_data()
    sub_name, count = data["subreddit"], data["count"]

    await callback.message.edit_text(f"🔍 Fetching {count} {sort} posts from r/{sub_name}...")

    try:
        posts = await _fetch_reddit_posts(sub_name, count, sort)
        if not posts:
            await callback.message.edit_text(f"⚠️ No video posts found in r/{sub_name}")
            return

        await callback.message.edit_text(f"🚀 Found {len(posts)} media posts. Queuing...")
        quality = db_user.settings.format_quality if db_user.settings else "720"

        async with get_db() as session:
            for url in posts:
                job = await crud.create_download_job(session, db_user.id, url, quality)
                await preflight_task.kiq(
                    url=url, user_id_str=str(db_user.id), job_id_str=str(job.id),
                    format_quality=quality, chat_id=callback.message.chat.id, message_id=0
                )
        await callback.message.reply(f"✅ Queued {len(posts)} videos from r/{sub_name}")
    except Exception as e:
        log.exception("reddit_bulk_failed", error=str(e))
        await callback.message.edit_text(f"❌ Failed to fetch from Reddit: {str(e)}")
    finally:
        await state.clear()
        await callback.answer()
