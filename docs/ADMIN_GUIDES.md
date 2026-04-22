# MEDDOWBOT Administrator Guides

This document provides essential instructions for configuring and monitoring your MEDDOWBOT instance.

---

## 1. BotFather Configuration Guide

Properly configuring your bot via [@BotFather](https://t.me/BotFather) ensures a professional user experience and enables all features correctly.

### 📋 Commands Setup
Send `/setcommands` to `@BotFather`, select your bot, and paste the following list:

```text
start - Start the bot and get welcome message
help - Show help and supported platforms
download - Download media from a link
quality - Set your preferred video quality
settings - Manage your personal preferences
history - View your recent download history
reddit - Bulk download media from a subreddit
cancel - Cancel the current active operation
```

### 📝 Description (About the Bot)
Send `/setdescription`. This text appears before a user starts the bot.
**Copy and paste:**
```text
🚀 MEDDOWBOT: The ultimate media downloader! 

Download video & audio from 1000+ sites including YouTube, Instagram, TikTok, Twitter (X), and Reddit. 

✨ Features:
• High-quality MP4/MP3 downloads
• Automatic FFmpeg compression
• Rapid Reddit bulk downloading
• Custom quality selection (360p to 4K)
• Search support
• Ad-free & Lightning fast

Paste a link to start or use /download. Support for large files up to 2GB via Local Bot API. Your all-in-one tool for saving social media content!
```

### ℹ️ About Text (Short Bio)
Send `/setabouttext`. This appears on the bot's profile page.
**Copy and paste:**
```text
The ultimate media downloader for Telegram. 1000+ sites supported. Fast, high-quality, and completely free.
```

### 🔒 Privacy & Groups
If you want to use the bot in groups:
1. Send `/setprivacy`.
2. Select your bot.
3. Set it to **Disabled** (this allows the bot to "see" all messages in groups, which is required if you want it to detect links automatically). 
   *Note: If you only want it to respond to commands, keep it **Enabled**.*

### 🌐 Domain (Optional)
If you have a website for the bot, use `/setdomain` to link it.

### ✅ Verification
To verify the setup:
1. Open your bot in Telegram.
2. Click the **Menu** button (left of the message input). All commands should appear with their descriptions.
3. Check the **"What can this bot do?"** section to see your description.

---

## 2. Uptime Monitoring & Health Check Guide

Monitoring ensures your bot is always ready to serve users. MEDDOWBOT includes a built-in health check endpoint.

### 🛠️ The `/health` Endpoint
MEDDOWBOT exposes a robust health check at `http://your-ip-or-domain:8080/health`.

**Response Format:**
```json
{
    "status": "ok",
    "redis": "ok",
    "database": "ok",
    "workers_alive": true,
    "uptime_seconds": 12345,
    "version": "1.0.0"
}
```

### 📈 Setting up UptimeRobot (Free Tier)
1. Log in to [UptimeRobot](https://uptimerobot.com/).
2. Click **+ Add New Monitor**.
3. **Monitor Type:** HTTP(s).
4. **Friendly Name:** `MEDDOWBOT Health`.
5. **URL (or IP):** `http://your-server-address:8080/health`.
6. **Monitoring Interval:** 5 minutes (Free tier).
7. **Monitor Timeout:** 30 seconds.
8. (Optional) **Custom HTTP Status:** You can configure it to look for `status: "ok"` in the JSON, but checking for HTTP 200 is usually sufficient.
9. Click **Create Monitor**.

### 💻 Implementation Details (Code)
For reference, the health handler is implemented using `aiohttp` in `bot/main.py`:

```python
async def health_handler(request: web.Request) -> web.Response:
    """Check health of vital services (Database, Redis)."""
    db_ok = False
    try:
        async with get_db() as session:
            await session.execute(select(1))
            db_ok = True
    except Exception as e:
        log.error("health_check_db_failed", error=str(e))

    redis_ok = False
    try:
        redis = get_redis()
        await redis.ping()
        redis_ok = True
    except Exception as e:
        log.error("health_check_redis_failed", error=str(e))

    # Workers check: Redis connectivity is the primary indicator
    workers_alive = redis_ok
    uptime_seconds = int((datetime.now(UTC) - START_TIME).total_seconds())

    data = {
        "status": "ok" if db_ok and redis_ok else "degraded",
        "redis": "ok" if redis_ok else "error",
        "database": "ok" if db_ok else "error",
        "workers_alive": workers_alive,
        "uptime_seconds": uptime_seconds,
        "version": settings.version,
    }

    status = 200 if db_ok and redis_ok else 503
    return web.json_response(data, status=status)
```

### 🚀 Integration
The handler is automatically registered in `bot/main.py`:
- In **Production**: It runs alongside the webhook.
- In **Development**: It runs on port `8080` while the bot uses polling.
