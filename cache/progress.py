from __future__ import annotations

import asyncio
import json
import time

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from cache.client import get_redis

log = structlog.get_logger(__name__)


async def publish_progress(
    job_id: str,
    percent: float,
    speed: str,
    eta: str,
) -> None:
    """
    Publish download progress to Redis Pub/Sub.

    Args:
        job_id: Unique identifier for the download job.
        percent: Download percentage (0-100).
        speed: Formatted speed string (e.g., "5.2 MiB/s").
        eta: Formatted ETA string (e.g., "00:30").
    """
    redis = get_redis()
    data = {
        "percent": percent,
        "speed": speed,
        "eta": eta,
        "timestamp": time.time(),
    }
    await redis.publish(f"progress:{job_id}", json.dumps(data))


async def start_progress_listener(
    job_id: str,
    bot: Bot,
    chat_id: int,
    message_id: int,
) -> None:
    """
    Listen for progress updates and update the Telegram message.
    Throttles updates to avoid Telegram rate limits.

    Args:
        job_id: Unique identifier for the download job.
        bot: Aiogram Bot instance.
        chat_id: Telegram chat ID.
        message_id: Telegram message ID to edit.
    """
    redis = get_redis()
    pubsub = redis.pubsub()
    channel = f"progress:{job_id}"

    await pubsub.subscribe(channel)
    log.info("Started progress listener", job_id=job_id, chat_id=chat_id)

    last_update_time = 0.0
    updates_count = 0
    MAX_UPDATES = 20
    UPDATE_INTERVAL = 3.0

    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                data = json.loads(message["data"])
                percent = data.get("percent", 0.0)
                speed = data.get("speed", "N/A")
                eta = data.get("eta", "N/A")

                now = time.time()
                # Throttle check
                if (now - last_update_time >= UPDATE_INTERVAL and updates_count < MAX_UPDATES) or percent >= 100:
                    text = f"📥 Downloading: {percent}% | {speed} | ETA: {eta}"

                    try:
                        await bot.edit_message_text(
                            text=text,
                            chat_id=chat_id,
                            message_id=message_id,
                        )
                        last_update_time = now
                        updates_count += 1
                    except TelegramRetryAfter as e:
                        await asyncio.sleep(e.retry_after)
                    except TelegramBadRequest as e:
                        if "message is not modified" not in str(e).lower():
                            log.error("Failed to edit progress message", error=str(e))
                    except Exception as e:
                        log.error("Unexpected error updating progress", error=str(e))

                if percent >= 100:
                    log.info("Progress reached 100%, stopping listener", job_id=job_id)
                    break

            except (json.JSONDecodeError, KeyError) as e:
                log.error("Failed to parse progress message", error=str(e))

    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        log.info("Progress listener stopped", job_id=job_id)
