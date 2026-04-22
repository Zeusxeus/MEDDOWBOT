from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
import structlog
from sqlalchemy import func, select, update

from config.settings import settings
from database.models import Proxy, ProxyStatus
from database.session import get_db

log = structlog.get_logger(__name__)


class ProxyPool:
    """
    Manager for the residential proxy pool.
    Handles selection, health tracking, and rotation.
    """

    def __init__(self) -> None:
        self._health_check_task: asyncio.Task | None = None
        self._semaphore = asyncio.Semaphore(10)

    async def start(self) -> None:
        """Start the background health check loop."""
        if self._health_check_task and not self._health_check_task.done():
            return

        log.info("starting_proxy_health_check_loop")
        self._health_check_task = asyncio.create_task(self._health_check_loop())

    async def stop(self) -> None:
        """Stop the background health check loop."""
        if self._health_check_task:
            log.info("stopping_proxy_health_check_loop")
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None

    async def get_proxy_for_url(self, url: str) -> Proxy | None:
        """
        Get a proxy for a specific URL based on settings and rotation strategy.
        Returns None if proxies are disabled or platform is excluded.
        """
        if not settings.proxy.enabled:
            return None

        domain = urlparse(url).netloc.lower()

        # Check exclusion list
        if any(platform in domain for platform in settings.proxy.no_proxy_platforms):
            log.debug("proxy_skipped_excluded_platform", domain=domain)
            return None

        # Check if proxy is forced for this platform
        is_forced = any(platform in domain for platform in settings.proxy.force_proxy_platforms)

        proxy = await self._select_proxy()

        if not proxy and is_forced:
            log.warning("proxy_forced_but_none_available", domain=domain)

        if proxy:
            # Update last_used_at and total_uses immediately to avoid same proxy being picked
            # multiple times in rapid succession for round_robin/least_used
            async with get_db() as session:
                await session.execute(
                    update(Proxy)
                    .where(Proxy.id == proxy.id)
                    .values(
                        last_used_at=datetime.now(timezone.utc),
                        total_uses=Proxy.total_uses + 1,
                    )
                )
            log.debug("proxy_selected", proxy_id=proxy.id, domain=domain)

        return proxy

    async def _select_proxy(self) -> Proxy | None:
        """Implement proxy selection based on configured strategy."""
        async with get_db() as session:
            stmt = select(Proxy).where(Proxy.status == ProxyStatus.ACTIVE)

            strategy = settings.proxy.rotation_strategy

            if strategy == "round_robin":
                stmt = stmt.order_by(Proxy.last_used_at.asc().nulls_first())
            elif strategy == "least_used":
                stmt = stmt.order_by(Proxy.total_uses.asc())
            elif strategy == "least_errors":
                # Handle division by zero by adding 1 to successes
                stmt = stmt.order_by((Proxy.total_failures / (Proxy.total_successes + 1.0)).asc())
            elif strategy == "random":
                stmt = stmt.order_by(func.random())
            else:
                # Default to round robin if unknown strategy
                stmt = stmt.order_by(Proxy.last_used_at.asc().nulls_first())

            result = await session.execute(stmt.limit(1))
            return result.scalar_one_or_none()

    async def record_proxy_success(self, proxy_id: uuid.UUID, latency_ms: float) -> None:
        """
        Record a successful proxy usage and update metrics.
        Uses EMA (Exponential Moving Average) with alpha=0.1 for latency.
        """
        async with get_db() as session:
            proxy = await session.get(Proxy, proxy_id)
            if not proxy:
                return

            # EMA calculation: new_avg = (1 - alpha) * old_avg + alpha * new_value
            alpha = 0.1
            if proxy.avg_latency_ms is None:
                proxy.avg_latency_ms = latency_ms
            else:
                proxy.avg_latency_ms = (1 - alpha) * proxy.avg_latency_ms + alpha * latency_ms

            proxy.total_successes += 1
            proxy.last_success_at = datetime.now(timezone.utc)
            proxy.consecutive_failures = 0
            # If it was DEAD or TESTING, mark it ACTIVE again if it works
            if proxy.status in (ProxyStatus.DEAD, ProxyStatus.TESTING):
                proxy.status = ProxyStatus.ACTIVE

            await session.commit()
            log.debug("proxy_success_recorded", proxy_id=proxy_id, latency=latency_ms)

    async def record_proxy_failure(self, proxy_id: uuid.UUID) -> None:
        """
        Record a failed proxy usage.
        Marks proxy as DEAD if consecutive_failures >= 3.
        """
        async with get_db() as session:
            proxy = await session.get(Proxy, proxy_id)
            if not proxy:
                return

            proxy.total_failures += 1
            proxy.consecutive_failures += 1

            if proxy.consecutive_failures >= 3:
                proxy.status = ProxyStatus.DEAD
                log.warning("proxy_marked_dead", proxy_id=proxy_id, failures=proxy.consecutive_failures)

            await session.commit()
            log.debug("proxy_failure_recorded", proxy_id=proxy_id, failures=proxy.consecutive_failures)

    async def _health_check_loop(self) -> None:
        """Background loop for periodic health checks."""
        while True:
            try:
                await self._run_health_checks()
            except Exception as e:
                log.exception("proxy_health_check_loop_error", error=str(e))

            await asyncio.sleep(settings.proxy.health_check_interval_seconds)

    async def _run_health_checks(self) -> None:
        """Run health checks on all non-disabled proxies concurrently."""
        async with get_db() as session:
            stmt = select(Proxy).where(
                Proxy.status.in_([ProxyStatus.ACTIVE, ProxyStatus.DEAD, ProxyStatus.TESTING])
            )
            result = await session.execute(stmt)
            proxies = result.scalars().all()

        if not proxies:
            return

        log.info("starting_concurrent_health_checks", count=len(proxies))
        tasks = [self._health_check_single(proxy) for proxy in proxies]
        await asyncio.gather(*tasks)
        log.info("finished_concurrent_health_checks")

    async def _health_check_single(self, proxy: Proxy) -> None:
        """Perform a single health check via httpx through the proxy."""
        async with self._semaphore:
            start_time = time.perf_counter()
            proxy_url = proxy.ytdlp_url

            try:
                async with httpx.AsyncClient(
                    proxy=proxy_url,
                    timeout=10.0,
                    follow_redirects=True,
                ) as client:
                    response = await client.get(settings.proxy.health_check_url)
                    response.raise_for_status()

                latency = (time.perf_counter() - start_time) * 1000
                await self.record_proxy_success(proxy.id, latency)

            except Exception as e:
                log.debug(
                    "proxy_health_check_failed",
                    proxy_id=proxy.id,
                    host=proxy.host,
                    error=str(e),
                )
                await self.record_proxy_failure(proxy.id)


# Singleton instance
proxy_pool = ProxyPool()
