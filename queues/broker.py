from __future__ import annotations

import structlog
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

from config.settings import settings

log = structlog.get_logger(__name__)

# Initialize Redis Result Backend
result_backend: RedisAsyncResultBackend = RedisAsyncResultBackend(
    redis_url=settings.redis.url,
    keep_results=True,
    result_ex_time=86400,  # 24 hours
)

# Initialize Taskiq Broker
# We use .with_result_backend() as recommended by Taskiq
broker: ListQueueBroker = ListQueueBroker(
    url=settings.redis.url,
).with_result_backend(result_backend)

# Set up logging for Taskiq
log.info("Taskiq broker initialized", redis_url=settings.redis.url)
