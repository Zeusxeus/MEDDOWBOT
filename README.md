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
MB_BOT__TOKEN=your_bot_token_from_botfather
MB_BOT__ADMIN_IDS=your_telegram_user_id
```

### Step 5: Start infrastructure
```bash
docker compose -f docker/docker-compose.yml up -d redis postgres
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

MEDDOWBOT uses Pydantic Settings for strict type-validated configuration. All variables **must** be prefixed with `MB_`.

### Environment
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MB_ENV` | `dev` | No | `dev`, `prod`, or `test` |

### Bot Settings
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MB_BOT__TOKEN` | — | **Yes** | Telegram Bot Token |
| `MB_BOT__ADMIN_IDS` | `[]` | **Yes** | Comma-separated list of Admin User IDs |
| `MB_BOT__WEBHOOK_URL` | — | Prod only | Base URL for webhooks |
| `MB_BOT__WEBHOOK_SECRET` | — | Prod only | Random secret for webhook security |

### Local Bot API (removes 50MB upload limit)
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MB_LOCAL_API__ENABLED` | `false` | No | Enables 2GB uploads |
| `MB_LOCAL_API__URL` | `http://localhost:8081` | No | Local API server URL |
| `MB_LOCAL_API__API_ID` | — | If enabled | Telegram API ID |
| `MB_LOCAL_API__API_HASH` | — | If enabled | Telegram API Hash |

### Database
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MB_DATABASE__URL` | — | **Yes** | Connection URL |
| `MB_DATABASE__POOL_SIZE` | `10` | No | Connection pool size |
| `MB_DATABASE__ECHO` | `false` | No | Log all SQL queries |

### Workers
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MB_WORKER__CONCURRENCY` | `3` | No | Simultaneous tasks per worker |

### Rate Limiting
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MB_RATE_LIMIT__REQUESTS_PER_MINUTE` | `10` | No | Max commands per minute |
| `MB_RATE_LIMIT__BURST` | `3` | No | Token bucket burst allowance |
| `MB_RATE_LIMIT__MAX_CONCURRENT_JOBS` | `2` | No | Simultaneous jobs per user |

### Proxy Pool
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MB_PROXY__ENABLED` | `true` | No | Enable residential proxy pool |
| `MB_PROXY__ROTATION_STRATEGY` | `round_robin` | No | Proxy selection algorithm |
| `MB_PROXY__FORCE_PROXY_PLATFORMS` | `youtube.com,youtu.be` | No | Domains that MUST use proxies |

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

## 🚀 Ubuntu VPS Setup (Step-by-Step)

Follow these steps to deploy MEDDOWBOT on a fresh Ubuntu 22.04/24.04 VPS.

### 1. System Preparation
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl ffmpeg
```

### 2. Install Docker & Compose
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

### 3. Install uv
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
- `MB_ENV=prod`
- `MB_BOT__TOKEN=your_token`
- `MB_BOT__ADMIN_IDS=your_id`
- `MB_DATABASE__URL=postgresql+asyncpg://botuser:botpass@postgres:5432/meddowbot`
- `MB_REDIS__URL=redis://redis:6379/0`

### 5. Deploy with Docker
```bash
docker compose -f docker/docker-compose.yml up -d
```

### 6. Initialize Database
```bash
docker compose -f docker/docker-compose.yml exec bot uv run alembic upgrade head
```

---

## 🔒 Security

- **SSRF Middleware:** Blocks private IP ranges.
- **Webhook Secrets:** Required for production webhooks.
- **Credential Masking:** Credentials are automatically masked in logs.
- **Disk Protection:** Refuses jobs if disk space is low.

---

## 🛠️ Development

### Testing
```bash
uv run pytest tests/ -v
```

---

## 🙏 Credits
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — Extraction engine.
- [aiogram](https://github.com/aiogram/aiogram) — Async framework.
- [Taskiq](https://github.com/taskiq-python/taskiq) — Task management.

---

*MEDDOWBOT — Download anything. From anywhere.*
