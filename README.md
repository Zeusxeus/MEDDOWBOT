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
MEDDOW_BOT_TOKEN=your_bot_token_from_botfather
MEDDOW_BOT_ADMIN_IDS=your_telegram_user_id
```

### Step 5: Start infrastructure
```bash
docker compose -f docker/docker-compose.yml up -d redis postgres
```

### Step 6: Run database migrations
```bash
uv run alembic upgrade head
```

---

## ⚙️ Configuration

MEDDOWBOT uses Pydantic Settings for strict type-validated configuration. All variables **must** be prefixed with `MEDDOW_`.

### Environment
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MEDDOW_ENV` | `dev` | No | `dev`, `prod`, or `test` |

### Bot Settings
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MEDDOW_BOT_TOKEN` | — | **Yes** | Telegram Bot Token |
| `MEDDOW_BOT_ADMIN_IDS` | `""` | **Yes** | Comma-separated list of Admin User IDs |
| `MEDDOW_BOT_WEBHOOK_URL` | — | Prod only | Base URL for webhooks |

### Local Bot API
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MEDDOW_LOCAL_API_ENABLED` | `false` | No | Enables 2GB uploads |
| `MEDDOW_LOCAL_API_URL` | `http://localhost:8081` | No | Local API server URL |

### Database
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MEDDOW_DATABASE_URL` | — | **Yes** | Connection URL |
| `MEDDOW_DATABASE_POOL_SIZE` | `10` | No | Connection pool size |

### Workers
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MEDDOW_WORKER_CONCURRENCY` | `3` | No | Simultaneous tasks per worker |

### Proxy Pool
| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MEDDOW_PROXY_ENABLED` | `true` | No | Enable residential proxy pool |
| `MEDDOW_PROXY_ROTATION_STRATEGY` | `round_robin` | No | Proxy selection algorithm |

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
- `MEDDOW_ENV=prod`
- `MEDDOW_BOT_TOKEN=your_token`
- `MEDDOW_BOT_ADMIN_IDS=your_id`
- `MEDDOW_DATABASE_URL=postgresql+asyncpg://botuser:botpass@postgres:5432/meddowbot`
- `MEDDOW_REDIS_URL=redis://redis:6379/0`

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
