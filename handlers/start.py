from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """
    Handle /start command.
    Welcomes the user and provides basic instructions.
    """
    welcome_text = (
        "👋 <b>Welcome to MEDDOWBOT!</b>\n\n"
        "I am a high-performance media downloader.\n\n"
        "📥 <b>To download:</b>\n"
        "Simply send me a link from YouTube, TikTok, Instagram, Twitter/X, "
        "Reddit, or 1000+ other sites.\n\n"
        "🛠 <b>Commands:</b>\n"
        "/download [url] — Download media\n"
        "/settings — Change quality and preferences\n"
        "/history — View your downloads\n"
        "/reddit — Bulk download from a subreddit\n"
        "/cancel — Stop current operation\n"
        "/help — Detailed instructions"
    )
    await message.answer(welcome_text)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """
    Handle /help command.
    Provides detailed help and list of supported sites.
    """
    help_text = (
        "❓ <b>How to use MEDDOWBOT</b>\n\n"
        "1️⃣ <b>Send a Link:</b> Paste any URL directly into the chat.\n"
        "2️⃣ <b>Wait:</b> I'll analyze the link and start downloading.\n"
        "3️⃣ <b>Receive:</b> You'll get the file directly in Telegram.\n\n"
        "📺 <b>Quality:</b>\n"
        "Use /settings to choose between 360p, 480p, 720p, 1080p, or Audio only.\n\n"
        "📁 <b>Large Files:</b>\n"
        "I support files up to 2GB thanks to Local Bot API.\n\n"
        "🚫 <b>Limits:</b>\n"
        "Please avoid spamming many links at once. Use /reddit for bulk downloads."
    )
    await message.answer(help_text)
