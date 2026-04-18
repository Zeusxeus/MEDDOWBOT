# MEDDOWBOT — Gemini CLI Workspace Configuration

## Project Identity
- **Name:** MEDDOWBOT (Media Downloader Bot)
- **Type:** Production-grade async Telegram bot
- **Stack:** Python 3.12, aiogram 3.x, Taskiq, Redis 7, PostgreSQL 16
- **Language:** Python (type-annotated, async-first, strict mypy)
- **Package manager:** uv (NOT pip, NOT poetry — always uv)
- **WSL path:** ~/projects/MEDDOWBOT
- **GitHub repo:** https://github.com/Zeusxeus/MEDDOWBOT

## Architecture Summary
Telegram webhook → aiogram middleware chain → Taskiq Redis queue → Worker pool
→ yt-dlp download → FFmpeg compress → Telegram upload (Local Bot API for 2GB)

Key design: handlers are 5 lines max. All heavy work in workers.
Workers use asyncio.to_thread() for yt-dlp, create_subprocess_exec for FFmpeg.
Redis is the queue, rate limiter, pub/sub, and FSM store in one.

## Absolute Rules (NEVER violate)
1. NEVER use `import os; os.environ["KEY"]` — always `from config.settings import settings`
2. NEVER call `requests` — always `httpx.AsyncClient` or `aiohttp`
3. NEVER use `subprocess.run()` — always `asyncio.create_subprocess_exec()`
4. NEVER call yt-dlp directly in handlers — always `asyncio.to_thread()` in workers
5. NEVER use `print()` — always `structlog`
6. NEVER use string concatenation for paths — always `pathlib.Path`
7. NEVER use bare `except:` — always `except SpecificException as e:`
8. NEVER hardcode tokens, passwords, or secrets — always .env + pydantic-settings
9. NEVER skip the `finally:` block for temp file cleanup
10. NEVER call yt-dlp without try/except wrapping DownloadError

## Code Style
- Python 3.12+ with `from __future__ import annotations`
- All functions: fully type-annotated
- All public functions: docstrings
- Line length: 100 chars (Ruff config)
- Async-first: if something blocks, it goes in to_thread()
- Test coverage minimum: 80%

## File Structure
MEDDOWBOT/
├── bot/main.py          ← startup only
├── handlers/            ← one file per command, 5 lines per handler
├── middleware/          ← ssrf, auth, rate_limit, logging
├── workers/             ← preflight.py, download.py
├── queue/broker.py      ← Taskiq singleton
├── database/            ← models, session, crud
├── cache/               ← redis client, rate_limiter, progress
├── utils/               ← ytdlp, ffmpeg, proxy, cookies, quota, upload
├── config/settings.py   ← Pydantic BaseSettings (single source of truth)
└── observability/       ← structlog, prometheus

## Current Phase
Phase 1: Foundation (database, config, Redis, health endpoint)
→ Update this when moving to next phase

## Proxy System
- Input format: host:port:username:password
- yt-dlp format: http://username:password@host:port
- Rotation: round_robin by default
- YouTube always uses proxy (force_proxy_platforms)
- Managed via /admin proxy add command (NEVER hardcode)

## Cookie System  
- Format: Netscape HTTP Cookie File (.txt from browser extension)
- Location: data/cookies/<platform>/<filename>.txt
- Never commit cookie files to git
- Upload via /admin cookie upload youtube

## Testing Rules
- No real Redis in tests → fakeredis
- No real DB in tests → SQLite :memory:
- No real Taskiq in tests → InMemoryBroker
- No real Telegram in tests → AsyncMock
- No real yt-dlp in tests → mock
- Run tests: uv run pytest tests/ -v

## Commands Quick Reference
```bash
uv sync --all-extras           # Install dependencies
uv run python -m bot.main      # Run bot (dev polling mode)
uv run pytest tests/ -v        # Run tests
uv run ruff check .            # Lint
uv run mypy .                  # Type check
docker compose up -d           # Start infrastructure
alembic upgrade head           # Run migrations
```
