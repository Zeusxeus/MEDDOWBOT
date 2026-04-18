from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# Prefix for all metrics
PREFIX = "meddowbot"

jobs_completed_total = Counter(
    f"{PREFIX}_jobs_completed_total",
    "Total number of successfully completed jobs",
    labelnames=["platform"],
)

jobs_failed_total = Counter(
    f"{PREFIX}_jobs_failed_total",
    "Total number of failed jobs",
    labelnames=["reason"],
)

job_duration_seconds = Histogram(
    f"{PREFIX}_job_duration_seconds",
    "Time taken to process a job",
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800),
)

bytes_served_total = Counter(
    f"{PREFIX}_bytes_served_total",
    "Total bytes sent to users",
)

proxy_pool_active_count = Gauge(
    f"{PREFIX}_proxy_pool_active_count",
    "Current number of healthy proxies in the pool",
)

rate_limited_total = Counter(
    f"{PREFIX}_rate_limited_total",
    "Total number of requests that were rate limited",
)

proxy_health_check_total = Counter(
    f"{PREFIX}_proxy_health_check_total",
    "Total number of proxy health checks",
    labelnames=["proxy", "result"],
)

proxy_health_check_duration = Histogram(
    f"{PREFIX}_proxy_health_check_duration",
    "Duration of proxy health checks",
    labelnames=["proxy"],
)

queue_depth = Gauge(
    f"{PREFIX}_queue_depth",
    "Current number of jobs in the queue",
)
