# 🚀 MEDDOWBOT (Media Downloader Bot)

MEDDOWBOT is a production-grade, asynchronous Telegram bot designed for high-performance media downloading. It leverages `yt-dlp` for extracting media from hundreds of platforms, `FFmpeg` for intelligent compression, and a robust `Taskiq` worker pool for scalable processing.

---

## ✨ Features

- **Multi-Platform Support:** Seamlessly download from YouTube, Instagram, TikTok, Twitter, Reddit, and more.
- **Bulk Reddit Downloads:** Crawl subreddits and download all media from top posts.
- **Intelligent Compression:** Automatically compresses videos to fit Telegram's 50MB limit (or supports up to 2GB with Local Bot API).
- **Asynchronous Architecture:** Built with `aiogram 3.x`, `Taskiq`, and `Redis` for non-blocking operations.
- **Proxy Pool:** Built-in rotation and health checking for residential proxies.
- **Cookie Management:** Easy upload and validation of Netscape cookie files for authenticated content.
- **Production Ready:** Supports both long-polling (dev) and Webhooks (prod).
- **Admin Dashboard:** Powerful command-line interface for managing users, proxies, and cookies.
- **Observability:** Structured logging with `structlog` and metrics via `Prometheus`.

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.12+
- Redis 7+
- PostgreSQL 16+
- FFmpeg

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/Zeusxeus/MEDDOWBOT.git
cd MEDDOWBOT

# Install dependencies using uv
uv sync --all-extras
```

### 3. Configuration
Copy the example environment file and fill in your details:
```bash
cp .env.example .env
```

### 4. Database Setup
```bash
uv run alembic upgrade head
```

### 5. Running
**Development (Polling):**
```bash
uv run python -m bot.main
```

**Worker Pool:**
```bash
uv run taskiq worker task_queue.broker:broker workers.download:download_task workers.preflight:preflight_task
```

---

## ⚙️ Configuration (.env)

| Variable | Description | Default |
|----------|-------------|---------|
| `ENV` | Environment (`dev`, `prod`, `test`) | `dev` |
| `BOT__TOKEN` | Telegram Bot API Token | Required |
| `BOT__ADMIN_IDS` | Comma-separated list of Admin IDs | Required |
| `BOT__WEBHOOK_URL` | Base URL for Webhooks (HTTPS) | Optional |
| `LOCAL_API__ENABLED`| Use Local Telegram Bot API (2GB uploads) | `false` |
| `DATABASE__URL` | PostgreSQL connection string | Required |
| `REDIS__URL` | Redis connection string | `redis://localhost:6379/0` |
| `PROXY__ENABLED` | Enable proxy rotation | `true` |
| `FFMPEG__TARGET_MB` | Target size for compressed videos | `45` |

---

## 🤖 Bot Commands

### User Commands
- `/start` - Initialize the bot and see welcome message.
- `/help` - Show available commands and usage.
- `/download <url>` - Manually trigger a download.
- `/cancel` - Cancel your most recent active job.
- `/quality` - Set your preferred video resolution.
- `/settings` - Manage your preferences (compression, ZIP, etc.).
- `/history` - View your recent download history.
- `/reddit <subreddit>` - Start a bulk download from a subreddit.

### Admin Commands
- `/admin stats` - View global system statistics.
- `/admin proxy add <host:port:user:pass>` - Add a proxy to the pool.
- `/admin cookie upload <platform>` - Upload a Netscape cookie file.
- `/admin ban <user_id>` - Ban a user from using the bot.

---

## 🌐 Proxies & Cookies

### Proxies
MEDDOWBOT supports residential proxy rotation. Use the `/admin proxy add` command to add proxies in the format `host:port:username:password`. The bot will automatically rotate through active proxies and disable "dead" ones.

### Cookies
For platforms like YouTube or Instagram, you can upload Netscape HTTP Cookie files (usually exported via browser extensions). Use `/admin cookie upload <platform>` and send the `.txt` file.

---

## 🛠 Tech Stack

- **Framework:** [aiogram 3.x](https://docs.aiogram.dev/)
- **Task Queue:** [Taskiq](https://taskiq-python.github.io/) + Redis
- **Database:** [PostgreSQL](https://www.postgresql.org/) + [SQLAlchemy 2.0](https://www.sqlalchemy.org/)
- **Migrations:** [Alembic](https://alembic.sqlalchemy.org/)
- **Media Extraction:** [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- **Processing:** [FFmpeg](https://ffmpeg.org/)
- **Package Manager:** [uv](https://github.com/astral-sh/uv)
- **Logging:** [structlog](https://www.structlog.org/)

---

## 📜 License
MIT License. See `LICENSE` for details.
