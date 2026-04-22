from __future__ import annotations

import structlog
from taskiq import TaskiqEvents, TaskiqState
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

from cache.client import init_redis
from config.settings import settings

log = structlog.get_logger(__name__)

# Initialize Redis Result Backend
result_backend: RedisAsyncResultBackend = RedisAsyncResultBackend(
    redis_url=settings.redis.url,
    keep_results=True,
    result_ex_time=86400,  # 24 hours
)

# Initialize Taskiq Broker
broker = ListQueueBroker(
    url=settings.redis.url,
).with_result_backend(result_backend)


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup_event(_: TaskiqState) -> None:
    """Initialize essential services on worker startup."""
    await init_redis()
    log.info("taskiq_worker_startup_complete")


log.info("taskiq_broker_initialized", url=settings.redis.url)
