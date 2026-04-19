from __future__ import annotations

import asyncio
import datetime
import pathlib
import uuid
from urllib.parse import urlparse

import structlog

from config.settings import settings
from database import crud
from database.models import CookieFile
from database.session import get_db

log = structlog.get_logger(__name__)


class CookieManager:
    """Manages yt-dlp cookie files and their lifecycle."""

    def __init__(self) -> None:
        """Initialize CookieManager and ensure directory structure exists."""
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Create necessary cookie directories."""
        for platform in settings.cookies.cookie_platforms:
            path = settings.cookies.path / platform
            path.mkdir(parents=True, exist_ok=True)

    async def get_cookie_file(self, platform_or_url: str) -> str | None:
        """
        Get the path to the active cookie file for a given platform or URL.

        Returns None if cookies are disabled, platform is not supported,
        or no active cookie file is found in the database.
        """
        if not settings.cookies.enabled:
            return None

        domain = self._normalize_domain(platform_or_url)
        platform = self._platform_key(domain)

        if platform not in settings.cookies.cookie_platforms:
            return None

        async with get_db() as session:
            cookie_record = await crud.get_active_cookie(session, platform)

        if not cookie_record:
            return None

        file_path = pathlib.Path(cookie_record.file_path)
        if not file_path.exists():
            log.warning("active_cookie_file_not_found", platform=platform, path=str(file_path))
            return None

        # Warning if expiring soon (< 7 days)
        if cookie_record.expires_at:
            time_until_expiry = cookie_record.expires_at - datetime.datetime.now(
                datetime.timezone.utc
            )
            if time_until_expiry < datetime.timedelta(days=7):
                log.warning(
                    "cookie_expiring_soon",
                    platform=platform,
                    expires_at=cookie_record.expires_at,
                    days_left=time_until_expiry.days,
                )

        return str(file_path)

    async def save_cookie_file(
        self, platform: str, content_bytes: bytes, uploaded_by_user_id: uuid.UUID
    ) -> tuple[bool, str]:
        """
        Validate, save, and activate a new cookie file.

        1. Validates Netscape format.
        2. Saves to a timestamped file.
        3. Validates functionality via yt-dlp --simulate.
        4. Updates database (deactivates old, records new).
        """
        try:
            content = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return False, "Failed to decode cookie file as UTF-8."

        is_valid_format, error_msg = self._validate_netscape_format(content)
        if not is_valid_format:
            return False, f"Invalid Netscape format: {error_msg}"

        if platform not in settings.cookies.cookie_platforms:
            return False, f"Platform '{platform}' is not in supported cookie platforms."

        expires_at = self._extract_earliest_expiry(content)
        if expires_at and expires_at < datetime.datetime.now(datetime.timezone.utc):
            return False, f"Cookies are already expired (expired at {expires_at})."

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}.txt"
        save_path = settings.cookies.path / platform / filename

        try:

            def _write_file() -> None:
                with open(save_path, "w", encoding="utf-8") as f:
                    f.write(content)

            await asyncio.to_thread(_write_file)
        except Exception as e:
            log.error("cookie_save_failed", error=str(e), path=str(save_path))
            return False, "Failed to save cookie file to disk."

        # Validate via yt-dlp
        test_url = self._get_test_url(platform)
        if test_url:
            is_working, validation_error = await self._test_cookie_file(str(save_path), test_url)
            if not is_working:
                # Cleanup failed file
                try:
                    await asyncio.to_thread(save_path.unlink, missing_ok=True)
                except Exception:
                    pass
                return False, f"Cookie validation failed: {validation_error}"

        # DB operations
        async with get_db() as session:
            await crud.deactivate_all_cookies(session, platform)
            new_cookie = CookieFile(
                platform=platform,
                filename=filename,
                is_active=True,
                is_valid=True,
                last_validated_at=datetime.datetime.now(datetime.timezone.utc),
                uploaded_by_user_id=uploaded_by_user_id,
                expires_at=expires_at,
            )
            session.add(new_cookie)
            # Session commit is handled by get_db() context manager

        log.info("cookie_activated", platform=platform, filename=filename)
        return True, "Cookie file successfully validated and activated."

    def _validate_netscape_format(self, content: str) -> tuple[bool, str | None]:
        """
        Validate that the content follows the Netscape cookie file format.
        7 tab-separated columns per line.
        """
        lines = content.strip().splitlines()
        if not lines:
            return False, "File is empty."

        data_lines_count = 0
        for i, line in enumerate(lines):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            fields = line.split("\t")
            if len(fields) != 7:
                return (
                    False,
                    f"Line {i+1} has {len(fields)} fields, expected 7 (tab-separated).",
                )
            data_lines_count += 1

        if data_lines_count == 0:
            return False, "No valid cookie data lines found."

        return True, None

    def _extract_earliest_expiry(self, content: str) -> datetime.datetime | None:
        """Parse the 5th column as Unix timestamp and find the minimum."""
        expiries: list[datetime.datetime] = []
        for line in content.strip().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            fields = line.split("\t")
            if len(fields) >= 5:
                try:
                    ts = int(fields[4])
                    if ts > 0:
                        # Some cookies use 0 or very large numbers for "never expire"
                        # We limit it to a reasonable future date for safety
                        if ts > 2147483647:  # Year 2038 problem
                            ts = 2147483647
                        expiries.append(
                            datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
                        )
                except (ValueError, OSError):
                    continue

        return min(expiries) if expiries else None

    def _normalize_domain(self, url_or_domain: str) -> str:
        """Extract netloc from URL or return lowercase domain."""
        if "://" in url_or_domain:
            parsed = urlparse(url_or_domain)
            domain = parsed.netloc.lower()
        else:
            domain = url_or_domain.lower()

        # Remove www.
        if domain.startswith("www."):
            domain = domain[4:]
        return domain

    def _platform_key(self, domain: str) -> str:
        """Map domains to platform keys."""
        mapping = {
            "youtube.com": "youtube",
            "youtu.be": "youtube",
            "instagram.com": "instagram",
            "twitter.com": "twitter",
            "x.com": "twitter",
            "tiktok.com": "tiktok",
        }
        # First check exact mapping
        if domain in mapping:
            return mapping[domain]

        # Then check if domain ends with any of the keys (e.g. m.youtube.com)
        for key_domain, platform in mapping.items():
            if domain.endswith(f".{key_domain}"):
                return platform

        # If it's already a platform key, return it
        if domain in settings.cookies.cookie_platforms:
            return domain

        return domain

    def _get_test_url(self, platform: str) -> str | None:
        """Return a safe URL to test cookies for a given platform."""
        urls = {
            "youtube": "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
            "instagram": "https://www.instagram.com/reels/C4p7OJyis8u/",
            "twitter": "https://twitter.com/X/status/1769800000000000000",
            "tiktok": "https://www.tiktok.com/@tiktok/video/7346859664673328427",
        }
        return urls.get(platform)

    async def _test_cookie_file(self, file_path: str, test_url: str) -> tuple[bool, str | None]:
        """Run yt-dlp --simulate to check if cookies are working."""
        cmd = [
            "yt-dlp",
            "--cookies",
            file_path,
            "--simulate",
            "--no-warnings",
            "--quiet",
            test_url,
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()

            if process.returncode == 0:
                return True, None

            error_msg = stderr.decode().strip()
            return False, error_msg or f"yt-dlp exited with code {process.returncode}"

        except Exception as e:
            return False, f"Failed to execute yt-dlp: {e}"


# Singleton instance
cookie_manager = CookieManager()
