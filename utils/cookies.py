from __future__ import annotations

import asyncio
import datetime
import pathlib
import uuid
from urllib.parse import urlparse

import structlog
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config.settings import settings
from database import crud
from database.models import CookieFile
from database.session import get_db
from utils.notify import notify_admins

log = structlog.get_logger(__name__)


class CookieManager:
    """Manages yt-dlp cookie files and their lifecycle."""

    def __init__(self) -> None:
        """Initialize CookieManager and ensure directory structure exists."""
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Create necessary cookie directories."""
        for platform in settings.cookies.cookie_platforms:
            path = settings.cookies.cookies_dir / platform
            path.mkdir(parents=True, exist_ok=True)

    async def get_cookie_file(self, url: str) -> str | None:
        """
        Get the absolute path to the active cookie file for a given URL.

        Steps:
        1. Extract domain and map to platform key.
        2. Check if cookies are enabled and platform is supported.
        3. Lookup active CookieFile in DB.
        4. Construct absolute path and verify file exists.
        5. Warn if expired but still return path.
        """
        if not settings.cookies.enabled:
            return None

        domain = self._normalize_domain(url)
        platform = self._platform_key(domain)

        if platform not in settings.cookies.cookie_platforms:
            log.debug("platform_not_in_cookie_platforms", platform=platform, url=url)
            return None

        async with get_db() as session:
            cookie_record = await crud.get_active_cookie(session, platform)

        if not cookie_record:
            log.debug("no_active_cookie_found", platform=platform)
            return None

        # Construct absolute path: settings.cookies.cookies_dir / platform / filename
        file_path = (
            pathlib.Path(settings.cookies.cookies_dir).absolute() / platform / cookie_record.filename
        )

        if not file_path.exists():
            log.warning("active_cookie_file_not_found_on_disk", platform=platform, path=str(file_path))
            return None

        # Check if expired
        if cookie_record.expires_at:
            now = datetime.datetime.now(datetime.timezone.utc)
            if cookie_record.expires_at < now:
                log.warning(
                    "cookie_file_expired",
                    platform=platform,
                    expires_at=cookie_record.expires_at,
                    path=str(file_path),
                )
                await self._notify_expiry(platform, "EXPIRED", cookie_record.expires_at)
            elif (cookie_record.expires_at - now) < datetime.timedelta(days=7):
                log.warning(
                    "cookie_expiring_soon",
                    platform=platform,
                    expires_at=cookie_record.expires_at,
                    days_left=(cookie_record.expires_at - now).days,
                )
                await self._notify_expiry(
                    platform,
                    f"expiring in {(cookie_record.expires_at - now).days} days",
                    cookie_record.expires_at,
                )

        return str(file_path)

    async def _notify_expiry(
        self, platform: str, status: str, expires_at: datetime.datetime | None
    ) -> None:
        """Notify admins about cookie expiry."""
        try:
            from utils.bot import get_bot
            bot = get_bot()

            expiry_str = str(expires_at) if expires_at else "Unknown"
            msg = f"🍪 <b>Cookie Warning: {platform}</b>\nStatus: <code>{status}</code>\nExpires: <code>{expiry_str}</code>"

            if not bot:
                bot = Bot(token=settings.bot.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
                await notify_admins(bot, msg)
                await bot.session.close()
            else:
                await notify_admins(bot, msg)
        except Exception as e:
            log.error("failed_to_notify_cookie_expiry", error=str(e))

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
        save_path = settings.cookies.cookies_dir / platform / filename

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

    async def validate_all_active_cookies(self) -> dict[str, bool]:
        """
        Validate all active cookies in the database and update their status.
        Returns a mapping of platform -> is_valid.
        """
        results = {}
        async with get_db() as session:
            for platform in settings.cookies.cookie_platforms:
                cookie_record = await crud.get_active_cookie(session, platform)
                if not cookie_record:
                    continue

                file_path = pathlib.Path(cookie_record.file_path)
                if not file_path.exists():
                    log.warning("cookie_file_missing", platform=platform, path=str(file_path))
                    cookie_record.is_valid = False
                    results[platform] = False
                    continue

                test_url = self._get_test_url(platform)
                if not test_url:
                    log.warning("no_test_url_for_platform", platform=platform)
                    results[platform] = True  # Assume OK if we can't test
                    continue

                is_working, error_msg = await self._test_cookie_file(str(file_path), test_url)
                cookie_record.is_valid = is_working
                cookie_record.last_validated_at = datetime.datetime.now(datetime.timezone.utc)
                if not is_working:
                    log.error("cookie_validation_failed", platform=platform, error=error_msg)
                    await self._notify_expiry(
                        platform, f"Validation failed: {error_msg}", cookie_record.expires_at
                    )

                results[platform] = is_working

        return results

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
            domain = (parsed.netloc or parsed.path).lower()
        else:
            domain = url_or_domain.lower()

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
            "reddit.com": "reddit",
            "redd.it": "reddit",
            "facebook.com": "facebook",
            "fb.watch": "facebook",
        }
        if domain in mapping:
            return mapping[domain]

        for key_domain, platform in mapping.items():
            if domain.endswith(f".{key_domain}"):
                return platform

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
            "reddit": "https://www.reddit.com/r/videos/comments/17vzmzz/the_oldest_known_video_of_london_1890/",
            "facebook": "https://www.facebook.com/facebook/videos/10153231339986729/",
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
