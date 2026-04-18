---
name: meddowbot-testing
description: >
  Testing procedures for MEDDOWBOT. Use when writing tests, running tests,
  checking coverage, or understanding the test setup.
  Triggers: "test", "pytest", "coverage", "write tests", "test setup".
---

# MEDDOWBOT Testing Guide

## Test Infrastructure
- pytest + pytest-asyncio (asyncio_mode = "auto" — no @pytest.mark.asyncio needed)
- fakeredis.aioredis — no real Redis needed
- SQLite :memory: — no real PostgreSQL needed
- InMemoryBroker — no real Taskiq needed
- AsyncMock(spec=Bot) — no real Telegram needed

## Run Tests
```bash
# All tests
uv run pytest tests/ -v

# Specific file
uv run pytest tests/utils/test_proxy.py -v

# With coverage
uv run pytest tests/ --cov=. --cov-report=term-missing

# Fast (no coverage, parallel)
uv run pytest tests/ -n auto
```

## Test File Location
tests/<same structure as source>/test_<filename>.py

## Fixtures (from tests/conftest.py)
- db_session: AsyncSession — in-memory SQLite
- fake_redis: FakeRedis — fake Redis
- in_memory_broker: InMemoryBroker — fake Taskiq
- mock_bot: AsyncMock — fake Telegram bot
- mock_message: MagicMock — fake message
- test_user: User — standard user with settings
- admin_user: User — user with is_admin=True

## Minimum Coverage: 80%
Focus on: middleware (auth, rate_limit), utils (proxy, cookies, ytdlp),
workers (preflight, download), database (crud).
