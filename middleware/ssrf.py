from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import urlparse

import structlog
from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

if TYPE_CHECKING:
    from collections.abc import Awaitable

log = structlog.get_logger(__name__)

PRIVATE_IP_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def is_private_ip(ip_str: str) -> bool:
    """Check if an IP address belongs to a private network."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return any(ip in network for network in PRIVATE_IP_RANGES)
    except ValueError:
        return False


async def is_ssrf_url(url: str) -> bool:
    """Resolve hostname and check if any of the IP addresses are private."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return False

        # Resolve hostname to IPs
        addr_info = await asyncio.to_thread(
            socket.getaddrinfo, hostname, None, proto=socket.IPPROTO_TCP
        )
        ips = {str(info[4][0]) for info in addr_info}

        for ip in ips:
            if is_private_ip(ip):
                log.warning("SSRF attempt detected", url=url, ip=ip)
                return True

        return False
    except Exception as e:
        log.error("SSRF check failed", url=url, error=str(e))
        return False


class SSRFProtectionMiddleware(BaseMiddleware):
    """Prevents Server-Side Request Forgery by blocking private IP ranges."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.text:
            return await handler(event, data)

        text = event.text.strip()
        if text.startswith(("http://", "https://")):
            if await is_ssrf_url(text):
                await event.answer("❌ Forbidden URL: Private network access is not allowed.")
                return

        return await handler(event, data)
