from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand
from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select

from cache.client import close_redis, get_redis, init_redis
from config.settings import settings
from database.models import Base, DownloadJob, JobStatus, User
from database.session import engine, get_db
from middleware.auth import AuthMiddleware
from middleware.logging import LoggingMiddleware
from middleware.rate_limit import RateLimitMiddleware
from middleware.ssrf import SSRFProtectionMiddleware
from observability.logging import setup_logging
from utils.cookies import cookie_manager
from utils.proxy import proxy_pool

log = structlog.get_logger(__name__)

# Module-level instances for access from workers and other modules
bot: Bot | None = None
bot_instance: Bot | None = None
dp: Dispatcher | None = None


async def _recover_stale_jobs() -> None:
    """
    Background task to find RUNNING jobs with old heartbeats and re-enqueue them.
    Prevents jobs from being stuck forever if a worker process crashes.
    """
    from workers.preflight import preflight_task

    while True:
        try:
            await asyncio.sleep(300)  # Check every 5 minutes
            log.info("stale_job_recovery_check")

            async with get_db() as session:
                # Find RUNNING jobs with heartbeat > 5 minutes old
                stale_threshold = datetime.now(UTC) - timedelta(minutes=5)
                stmt = (
                    select(DownloadJob, User.telegram_id)
                    .join(User, DownloadJob.user_id == User.id)
                    .where(
                        DownloadJob.status == JobStatus.RUNNING,
                        DownloadJob.heartbeat_at < stale_threshold,
                    )
                )
                result = await session.execute(stmt)
                stale_jobs = result.all()

                for job, telegram_id in stale_jobs:
                    log.warning(
                        "recovering_stale_job",
                        job_id=job.id,
                        telegram_id=telegram_id,
                        last_heartbeat=job.heartbeat_at,
                    )

                    # Update heartbeat and retry count to avoid immediate re-pickup
                    job.heartbeat_at = datetime.now(UTC)
                    job.retry_count += 1

                    if job.retry_count > 3:
                        log.error("job_max_recovery_retries_exceeded", job_id=job.id)
                        job.status = JobStatus.FAILED
                        job.error_message = "Max recovery retries exceeded. Worker probably crashed."
                        continue

                    # Re-enqueue preflight task
                    # We use message_id=0 which will cause _notify_user to send a new message
                    await preflight_task.kiq(
                        url=job.url,
                        user_id_str=str(job.user_id),
                        job_id_str=str(job.id),
                        format_quality=job.format_requested or "720",
                        chat_id=telegram_id,
                        message_id=0,
                    )

                await session.commit()
        except Exception as e:
            log.exception("stale_job_recovery_error", error=str(e))


async def webhook_handler(request: web.Request) -> web.Response:
    """Handle incoming updates from Telegram via webhook."""
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret != settings.bot.webhook_secret:
        log.warning("invalid_webhook_secret", received=secret)
        return web.Response(status=403)

    if bot is None or dp is None:
        return web.Response(status=503)

    update_data = await request.json()
    update = types.Update.model_validate(update_data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return web.Response()


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

    status = 200 if db_ok and redis_ok else 503
    return web.json_response({"database": db_ok, "redis": redis_ok}, status=status)


async def metrics_handler(request: web.Request) -> web.Response:
    """Prometheus metrics endpoint."""
    return web.Response(body=generate_latest(), content_type=CONTENT_TYPE_LATEST)


async def startup(app: web.Application) -> None:
    """Initialize all services and bot components."""
    global bot, bot_instance, dp

    setup_logging()
    log.info("starting_meddowbot", env=settings.env)

    # 1. Create DB tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("database_tables_ensured")

    # 2. Init Redis
    await init_redis()

    # 3. Start Proxy Pool
    await proxy_pool.start()

    # 4. Validate cookies if enabled
    if settings.cookies.enabled and settings.cookies.validate_on_startup:
        log.info("validating_cookies_on_startup")
        await cookie_manager.validate_all_active_cookies()

    # 5. Initialize Bot
    bot_kwargs: dict[str, Any] = {}
    if settings.bot.use_local_api:
        # aiogram 3.x expects full base url including /bot
        bot_kwargs["base_url"] = f"{settings.local_api.base_url}/bot"

    bot = Bot(token=settings.bot.token, **bot_kwargs)
    bot_instance = bot

    # 5. Initialize Dispatcher with Redis storage
    storage = RedisStorage(get_redis())
    dp = Dispatcher(storage=storage)

    # 6. Register Middlewares (Order: SSRF → Auth → RateLimit → Logging)
    # outer_middleware runs for every update, even if no handler matches
    dp.update.outer_middleware(SSRFProtectionMiddleware())
    dp.update.outer_middleware(AuthMiddleware())
    dp.update.outer_middleware(RateLimitMiddleware())
    dp.update.outer_middleware(LoggingMiddleware())

    # 7. Include Routers
    from handlers import router as main_router

    dp.include_router(main_router)

    # 8. Set Bot Commands
    await bot.set_my_commands(
        [
            BotCommand(command="download", description="Download media from URL"),
            BotCommand(command="settings", description="Change your preferences"),
            BotCommand(command="history", description="Show your recent downloads"),
            BotCommand(command="reddit", description="Bulk download from subreddit"),
            BotCommand(command="help", description="How to use the bot"),
        ]
    )

    # 9. Set Webhook in production
    if settings.env == "prod":
        webhook_url = f"{settings.bot.webhook_url}/webhook"
        log.info("setting_webhook", url=webhook_url)
        await bot.set_webhook(
            url=webhook_url,
            secret_token=settings.bot.webhook_secret or "",
            drop_pending_updates=True,
        )

    # 10. Start recovery task
    asyncio.create_task(_recover_stale_jobs())
    log.info("startup_complete")


async def shutdown(app: web.Application) -> None:
    """Graceful shutdown of all services."""
    log.info("shutting_down_meddowbot")

    if settings.env == "prod" and bot:
        log.info("deleting_webhook")
        await bot.delete_webhook()

    if bot:
        await bot.session.close()

    await proxy_pool.stop()
    await close_redis()
    await engine.dispose()
    log.info("shutdown_complete")


async def run_polling() -> None:
    """Run bot in polling mode (for development)."""
    # Create a dummy app for compatibility
    app = web.Application()
    await startup(app)
    try:
        if dp and bot:
            log.info("starting_polling")
            await dp.start_polling(bot)
    finally:
        await shutdown(app)


def main() -> None:
    """Entry point for the application."""
    if settings.env == "prod":
        app = web.Application()
        app.router.add_post("/webhook", webhook_handler)
        app.router.add_get("/health", health_handler)
        app.router.add_get("/metrics", metrics_handler)

        app.on_startup.append(startup)  # type: ignore[arg-type]
        app.on_cleanup.append(shutdown)  # type: ignore[arg-type]

        log.info("starting_aiohttp_server", port=8080)
        web.run_app(app, host="0.0.0.0", port=8080)
    else:
        # Run polling mode for development
        try:
            asyncio.run(run_polling())
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
