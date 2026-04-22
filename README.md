# MEDDOWBOT

**Production-grade Media Downloader Bot for Telegram.**

MEDDOWBOT is a high-performance, asynchronous Telegram bot designed to download media from over 1000+ websites with ease. Built with a distributed worker architecture, it handles heavy video processing tasks without blocking the bot's responsiveness, making it the ultimate tool for personal or community media archiving.

![Python](https://img.shields.io/badge/python-3.12-blue)
![aiogram](https://img.shields.io/badge/aiogram-3.x-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Docker](https://img.shields.io/badge/docker-ready-blue)

---

## ✨ Features

### 📥 Downloads
- **1000+ Sites Supported:** Powered by `yt-dlp`, MEDDOWBOT can download from YouTube, Instagram, TikTok, Twitter/X, Reddit, Facebook, Twitch, and many more.
- **Smart Quality Selection:** Choose between 360p, 480p, 720p, 1080p, audio-only, or "Best Available" via `/quality` or settings.
- **Real-time Progress:** Stay informed with live download/upload progress bars.
- **Quota Safeguards:** Large file warnings for files >200MB and disk space checks before starting jobs.
- **Instant Re-send:** Intelligent file caching based on URL hashes means if someone asks for a video already in the database, it's delivered instantly without re-downloading.
- **Auto-Conversion:** Sophisticated FFmpeg pipeline ensures everything is delivered as Telegram-native MP4.

### 🛡️ Anti-Bot Protection
- **Residential Proxy Pool:** Built-in support for proxy rotation with four strategies: `round_robin`, `random`, `least_used`, and `least_errors`.
- **YouTube Cookie Auth:** Simple administrative interface to upload Netscape cookie files, allowing you to download age-restricted or private content.
- **Self-Healing:** Automatic proxy health checks every 5 minutes with dead-proxy cooldown and auto-recovery.

### ⚡ Architecture
- **Non-Blocking Design:** Handlers only validate and enqueue; all heavy lifting is done in Taskiq workers.
- **Durable Job Queue:** Redis-backed persistence ensures that jobs survive bot crashes or system restarts.
- **Horizontally Scalable:** Scale processing power by spinning up additional worker containers with a single command.
- **Atomic Rate Limiting:** Lua-based token bucket rate limiting in Redis prevents bot abuse and race conditions.
- **Security-First:** Built-in SSRF protection blocks download requests to private IP ranges and internal network addresses.

### 🔧 Admin Dashboard
- **Live Statistics:** Track total users, active jobs, top platforms, and system success rates.
- **User Management:** Ban/unban users, view their download history, and set per-user rate limits.
- **Queue Control:** Monitor live job queue depth and clear pending jobs if needed.
- **Proxy & Cookie Management:** Add/Remove proxies and upload/validate cookie files via interactive menus.
- **Global Broadcast:** Send messages or system announcements to all bot users.
- **System Health:** Real-time monitoring of CPU, RAM, Disk usage, and database connection pools.

---

## 🏗️ Architecture

```
User sends URL
│
▼
Telegram → aiogram
│
▼
Middleware Chain:
├── SSRF Protection (blocks private IPs)
├── Auth (upsert user, check ban status)
├── Rate Limit (Redis Lua token bucket)
└── Logging (structlog context binding)
│
▼
Handler (< 15 lines — validates + enqueues)
│
▼
Redis Queue (Taskiq)
│
▼
Worker Pool
├── Preflight Task: fetch metadata, check cache, select optimal format
└── Download Task: download → compress → upload via Local Bot API → notify
│
▼
Telegram delivers file to user
```

### Why this design?
- **Tiny Handlers:** Since media downloads can take anywhere from 10 to 600 seconds, handlers never wait. They return a "Queued" status message immediately.
- **Reliable Recovery:** Using a Redis-backed queue (Taskiq) means if the server reboots, the workers pick up exactly where they left off.
- **Scalable Processing:** You can run 1 bot container and 10 worker containers on different servers to handle thousands of requests.
- **Efficient Delivery:** Preflight checks the database first; if a URL has been downloaded before, it sends the existing Telegram `file_id` instantly.

---

## 🚀 Quick Start

### Prerequisites
- **Docker + Docker Compose**
- **Python 3.12+**
- **uv package manager**
- **FFmpeg** installed on host (if running locally)
- A **Telegram Bot Token** from [@BotFather](https://t.me/botfather)
- Your **Telegram User ID** (from [@userinfobot](https://t.me/userinfobot))

### Step 1: Clone the repository
```bash
git clone https://github.com/Zeusxeus/MEDDOWBOT.git
cd MEDDOWBOT
```

### Step 2: Install uv
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

### Step 3: Install dependencies
```bash
uv sync --all-extras
```

### Step 4: Create your .env file
```bash
cp .env.example .env
nano .env
```
**Minimum required values:**
```bash
BOT__TOKEN=your_bot_token_from_botfather
BOT__ADMIN_IDS=your_telegram_user_id
```

### Step 5: Start infrastructure
```bash
docker compose up -d redis postgres
```

### Step 6: Run database migrations
```bash
uv run alembic upgrade head
```

### Step 7: Start the bot (development mode)
Open **two** terminals:

**Terminal 1 — Bot:**
```bash
uv run python -m bot.main
```

**Terminal 2 — Worker:**
```bash
uv run taskiq worker task_queue.broker:broker workers.preflight workers.download
```

---

## ⚙️ Configuration

MEDDOWBOT uses Pydantic Settings for strict type-validated configuration. You can set these in your `.env` file.

### Environment
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `ENV` | `dev` | No | `dev`, `prod`, or `test` |

### Bot Settings
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `BOT__TOKEN` | — | **Yes** | Telegram Bot Token |
| `BOT__ADMIN_IDS` | `[]` | **Yes** | Comma-separated list of Admin User IDs |
| `BOT__WEBHOOK_URL` | — | Prod only | Base URL for webhooks (e.g. `https://bot.example.com`) |
| `BOT__WEBHOOK_SECRET` | — | Prod only | Random 32+ char secret for webhook security |

### Local Bot API (removes 50MB upload limit)
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `LOCAL_API__ENABLED` | `false` | No | Enables 2GB uploads and faster delivery |
| `LOCAL_API__URL` | `http://localhost:8081` | No | Local Bot API server URL |
| `LOCAL_API__API_ID` | — | If enabled | Your Telegram API ID from my.telegram.org |
| `LOCAL_API__API_HASH` | — | If enabled | Your Telegram API Hash from my.telegram.org |

### Database
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `DATABASE__URL` | — | **Yes** | Connection URL (SQLite or PostgreSQL) |
| `DATABASE__POOL_SIZE` | `10` | No | Connection pool size (SQLAlchemy) |
| `DATABASE__ECHO` | `false` | No | Log all SQL queries |

**Production database URL format:**
`DATABASE__URL=postgresql+asyncpg://user:pass@host:5432/db`

### Workers
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `WORKER__CONCURRENCY` | `3` | No | Simultaneous tasks per worker process |
| `WORKER__PREFETCH` | `1` | No | How many tasks to buffer from queue |

### Rate Limiting
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `RATE_LIMIT__REQUESTS_PER_MINUTE` | `10` | No | Max commands per minute per user |
| `RATE_LIMIT__BURST` | `3` | No | Token bucket burst allowance |
| `RATE_LIMIT__MAX_CONCURRENT_JOBS` | `2` | No | Simultaneous jobs per user |

### Disk & FFmpeg
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `DISK__TEMP_PATH` | `data/temp` | No | Temporary work directory |
| `DISK__MIN_FREE_GB` | `2.0` | No | Space to reserve on disk |
| `FFMPEG__TARGET_MB` | `45` | No | Target compressed size |
| `FFMPEG__MAX_SIZE_MB` | `49` | No | Hard limit for standard API uploads |
| `FFMPEG__LARGE_FILE_WARN_MB` | `200` | No | Threshold for large file warnings |
| `FFMPEG__HW_ACCEL` | `auto` | No | GPU acceleration (auto, nvenc, vaapi, none) |

### Proxy Pool
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `PROXY_POOL__ENABLED` | `true` | No | Enable residential proxy pool |
| `PROXY_POOL__ROTATION_STRATEGY` | `round_robin` | No | Proxy selection algorithm |
| `PROXY_POOL__FORCE_PROXY_PLATFORMS` | `youtube.com,youtu.be` | No | Domains that MUST use proxies |

---

## 📋 Bot Commands

### User Commands
| Command | Description |
|---------|-------------|
| `/start` | Welcome and instructions |
| `/help` | Detailed command list |
| `/download [url]` | Explicitly download media (or just send URL) |
| `/quality` | Interactive quality selector |
| `/settings` | Open personal preference panel |
| `/history` | View your previous downloads |
| `/reddit` | Interactive bulk download from subreddits |
| `/cancel` | Stop your currently active job |

### Admin Commands
*Only accessible by IDs in `BOT__ADMIN_IDS`.*

| Command | Description |
|---------|-------------|
| `/admin` | Main Management Dashboard |
| `/admin stats` | Global system statistics |
| `/admin users` | User list, search, and moderation |
| `/admin proxy add` | Add proxy: `host:port:user:pass` |
| `/admin proxy list` | Monitor proxy latency and health |
| `/admin cookie upload` | Upload Netscape format `.txt` cookies |
| `/admin broadcast` | Send message to all active users |
| `/admin system` | System resources and worker status |

---

## 🌐 Adding Proxies

Residential proxies are essential for bypassing site-level bot detection.

**Add via bot command:**
`/admin proxy add 1.2.3.4:8080:username:password`

**Rotation strategies:**
- `round_robin`: Cycles through all proxies (fair distribution).
- `least_used`: Picks proxy with lowest total successful uses.
- `least_errors`: Picks proxy with the best historical reliability.

Proxies are automatically health-checked every 5 minutes. If a proxy fails 3 times consecutively, it's moved to a 10-minute cooldown.

---

## 🍪 YouTube Cookie Authentication

Some platforms require cookies to verify age or account status.

1. Install **"Get cookies.txt LOCALLY"** browser extension.
2. Log into YouTube in your browser.
3. Export cookies for `youtube.com` as a `.txt` file.
4. Send `/admin cookie upload youtube` to the bot.
5. Upload the exported file as a **Document**.

The bot will automatically use these cookies for all future YouTube downloads.

---

## 🐳 Docker Deployment

### Development Stack
Starts only the necessary backing services:
```bash
docker compose -f docker/docker-compose.yml up -d redis postgres
```

### Production Stack
Starts Bot, Worker, Redis, Postgres, Telegram-Bot-API, Prometheus, and Caddy:
```bash
docker compose -f docker/docker-compose.yml up -d
```

### Scaling Workers
```bash
docker compose -f docker/docker-compose.yml up -d --scale worker=5
```

---

## 🚀 Ubuntu VPS Setup (Step-by-Step)

Follow these steps to deploy MEDDOWBOT on a fresh Ubuntu 22.04/24.04 VPS.

### 1. System Preparation
Update your package list and install basic requirements:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl ffmpeg
```

### 2. Install Docker & Compose
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and log back in for group changes to take effect
```

### 3. Install uv (Fast Python Package Manager)
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env
```

### 4. Clone and Configure
```bash
git clone https://github.com/Zeusxeus/MEDDOWBOT.git
cd MEDDOWBOT
cp .env.example .env
nano .env
```

**Crucial Production Settings:**
- `ENV=prod`
- `BOT__TOKEN=your_token`
- `BOT__ADMIN_IDS=your_id`
- `DATABASE__URL=postgresql+asyncpg://botuser:botpass@postgres:5432/meddowbot`
- `REDIS__URL=redis://redis:6379/0`

### 5. Deploy with Docker
MEDDOWBOT is fully containerized. To start the entire stack (Bot, Worker pool, Redis, Postgres):

```bash
docker compose -f docker/docker-compose.yml up -d
```

### 6. Initialize Database
Run migrations inside the running bot container:
```bash
docker compose -f docker/docker-compose.yml exec bot uv run alembic upgrade head
```

### 7. Post-Setup Verification
Check if all containers are healthy:
```bash
docker compose -f docker/docker-compose.yml ps
```
Visit `http://your-vps-ip:8080/health` to confirm the API and database connections are active.

---

## 🔒 Security

- **SSRF Middleware:** All incoming URLs are checked against private IP ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`) before being passed to workers.
- **Webhook Secrets:** Production webhooks require a secret token provided by Telegram.
- **Credential Masking:** Proxy and Database credentials are automatically masked in logs.
- **Disk Protection:** The bot refuses new jobs if free disk space falls below `DISK__MIN_FREE_GB`.

---

## 🛠️ Development

### Testing
```bash
uv run pytest tests/ -v
```

### Linting & Types
```bash
uv run ruff check .
uv run mypy .
```

### Adding Dependencies
```bash
uv add <package_name>
```

---

## 🧰 Tech Stack
- **Bot Framework:** [aiogram 3.13](https://docs.aiogram.dev/)
- **Task Queue:** [Taskiq](https://taskiq-python.github.io/) + Redis
- **Database:** [PostgreSQL 16](https://www.postgresql.org/) + [SQLAlchemy 2.0](https://www.sqlalchemy.org/)
- **Extractions:** [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- **Processing:** [FFmpeg](https://ffmpeg.org/)
- **Config:** [Pydantic Settings](https://docs.pydantic.dev/latest/usage/pydantic_settings/)
- **Monitoring:** [Prometheus](https://prometheus.io/)
- **Package Manager:** [uv](https://github.com/astral-sh/uv)

---

## 🙏 Credits
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — The heart of extraction.
- [aiogram](https://github.com/aiogram/aiogram) — The async framework.
- [Taskiq](https://github.com/taskiq-python/taskiq) — Distributed task management.

---

*MEDDOWBOT — Download anything. From anywhere.*
