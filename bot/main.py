from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand
from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select

from cache.client import close_redis, get_redis, init_redis
from config.settings import settings
from database.models import Base, DownloadJob, JobStatus, User
from database.session import engine, get_db
from handlers import (
    admin_router,
    cancel_router,
    download_router,
    history_router,
    reddit_router,
    settings_router,
    start_router,
)
from middleware.auth import AuthMiddleware
from middleware.logging import LoggingMiddleware
from middleware.rate_limit import RateLimitMiddleware
from middleware.ssrf import SSRFProtectionMiddleware
from observability.logging import setup_logging
from utils.cookies import cookie_manager
from utils.proxy import proxy_pool

log = structlog.get_logger(__name__)

# Module-level instances
bot: Bot | None = None
bot_instance: Bot | None = None  # Added for compatibility with utils
dp: Dispatcher | None = None
START_TIME = datetime.now(UTC)


async def _recover_stale_jobs() -> None:
    """Find RUNNING jobs with old heartbeats and re-enqueue them."""
    from workers.preflight import preflight_task

    while True:
        try:
            await asyncio.sleep(300)
            async with get_db() as session:
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
                for job, telegram_id in result.all():
                    log.warning("recovering_stale_job", job_id=job.id)
                    job.heartbeat_at = datetime.now(UTC)
                    job.retry_count += 1
                    if job.retry_count > 3:
                        job.status = JobStatus.FAILED
                        job.error_message = "Max recovery retries exceeded."
                        continue

                    await preflight_task.kiq(
                        url=job.url, user_id_str=str(job.user_id), job_id_str=str(job.id),
                        format_quality=job.format_requested or "720",
                        chat_id=telegram_id, message_id=0,
                    )
                await session.commit()
        except Exception as e:
            log.exception("stale_job_recovery_error", error=str(e))


async def webhook_handler(request: web.Request) -> web.Response:
    """Handle incoming updates via webhook."""
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret != settings.bot.webhook_secret:
        return web.Response(status=403)

    if bot is None or dp is None:
        return web.Response(status=503)

    update_data = await request.json()
    update = types.Update.model_validate(update_data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return web.Response()


async def health_handler(request: web.Request) -> web.Response:
    """Check health of vital services."""
    try:
        async with get_db() as session:
            await session.execute(select(1))
        await get_redis().ping()
        return web.json_response({"status": "ok", "version": settings.version})
    except Exception as e:
        log.error("health_check_failed", error=str(e))
        return web.json_response({"status": "error"}, status=503)


async def metrics_handler(request: web.Request) -> web.Response:
    """Prometheus metrics endpoint."""
    return web.Response(body=generate_latest(), content_type=CONTENT_TYPE_LATEST)


async def startup(app: web.Application) -> None:
    """Initialize all services and bot components."""
    global bot, bot_instance, dp
    setup_logging()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await init_redis()
    await proxy_pool.start()
    if settings.cookies.enabled and settings.cookies.validate_on_startup:
        await cookie_manager.validate_all_active_cookies()

    base_url = f"{settings.local_api.url}/bot" if settings.local_api.enabled else None
    bot = Bot(
        token=settings.bot.token,
        default=DefaultBotProperties(parse_mode="HTML"),
        base_url=base_url
    )
    bot_instance = bot
    dp = Dispatcher(storage=RedisStorage(get_redis()))

    # Middleware
    dp.update.outer_middleware(SSRFProtectionMiddleware())
    dp.update.outer_middleware(AuthMiddleware())
    dp.update.outer_middleware(RateLimitMiddleware())
    dp.update.outer_middleware(LoggingMiddleware())

    # Routers (Order: Admin -> General -> Specific -> Catch-all)
    dp.include_router(admin_router)
    dp.include_router(start_router)
    dp.include_router(cancel_router)
    dp.include_router(settings_router)
    dp.include_router(history_router)
    dp.include_router(reddit_router)
    dp.include_router(download_router)

    # Commands
    await bot.set_my_commands([
        BotCommand(command="start", description="Start and help"),
        BotCommand(command="help", description="How to use"),
        BotCommand(command="download", description="Download from URL"),
        BotCommand(command="settings", description="Your preferences"),
        BotCommand(command="history", description="Download history"),
        BotCommand(command="reddit", description="Bulk reddit download"),
        BotCommand(command="cancel", description="Cancel active job"),
    ])

    if settings.env == "prod":
        await bot.set_webhook(
            url=f"{settings.bot.webhook_url}/webhook",
            secret_token=settings.bot.webhook_secret or "",
            drop_pending_updates=True,
        )
    asyncio.create_task(_recover_stale_jobs())
    log.info("startup_complete")


async def shutdown(app: web.Application) -> None:
    """Graceful shutdown."""
    if settings.env == "prod" and bot:
        await bot.delete_webhook()
    if bot:
        await bot.session.close()
    await proxy_pool.stop()
    await close_redis()
    await engine.dispose()
    log.info("shutdown_complete")


async def run_polling() -> None:
    """Run bot in polling mode."""
    app = web.Application()
    app.router.add_get("/health", health_handler)
    app.router.add_get("/metrics", metrics_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", settings.obs.metrics_port).start()
    await startup(app)
    try:
        if dp and bot:
            await dp.start_polling(bot)
    finally:
        await shutdown(app)
        await runner.cleanup()


def main() -> None:
    """Entry point."""
    if settings.env == "prod":
        app = web.Application()
        app.router.add_post("/webhook", webhook_handler)
        app.router.add_get("/health", health_handler)
        app.router.add_get("/metrics", metrics_handler)
        app.on_startup.append(startup)  # type: ignore
        app.on_cleanup.append(shutdown)  # type: ignore
        web.run_app(app, host="0.0.0.0", port=8080)
    else:
        try:
            asyncio.run(run_polling())
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
