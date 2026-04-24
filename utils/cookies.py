from __future__ import annotations

import asyncio
import datetime
import os
import pathlib
import shutil
import uuid
from urllib.parse import urlparse

import structlog
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy import select

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

    async def discover_local_cookies(self) -> None:
        """Scan cookies directory and register files in DB if missing."""
        log.info("starting_cookie_discovery")
        async with get_db() as session:
            for platform in settings.cookies.cookie_platforms:
                plat_dir = settings.cookies.cookies_dir / platform
                if not plat_dir.exists():
                    continue

                for f in plat_dir.glob("*.txt"):
                    # Check if already in DB
                    stmt = select(CookieFile).where(CookieFile.platform == platform, CookieFile.filename == f.name)
                    result = await session.execute(stmt)
                    if not result.scalar_one_or_none():
                        log.info("registering_found_cookie", platform=platform, file=f.name)
                        new_cookie = CookieFile(
                            platform=platform,
                            filename=f.name,
                            is_active=True,
                            is_valid=True,
                            last_validated_at=datetime.datetime.now(datetime.timezone.utc),
                        )
                        # Deactivate others for this platform first
                        await crud.deactivate_all_cookies(session, platform)
                        session.add(new_cookie)
            await session.commit()

    async def get_cookie_file(self, url: str) -> str | None:
        """Get the absolute path to the active cookie file for a given URL."""
        if not settings.cookies.enabled:
            log.debug("cookie_system_disabled")
            return None

        domain = self._normalize_domain(url)
        platform = self._platform_key(domain)
        log.debug("checking_cookies_for_platform", platform=platform, domain=domain)

        if platform not in settings.cookies.cookie_platforms:
            log.debug("platform_not_supported_for_cookies", platform=platform, supported=settings.cookies.cookie_platforms)
            return None

        async with get_db() as session:
            cookie_record = await crud.get_active_cookie(session, platform)

        if not cookie_record:
            log.debug("no_active_cookie_in_db", platform=platform)
            return None

        file_path = (
            pathlib.Path(settings.cookies.cookies_dir).absolute() / platform / cookie_record.filename
        )

        if not file_path.exists():
            log.error("cookie_file_missing_on_disk", platform=platform, path=str(file_path))
            return None

        log.debug("found_active_cookie", platform=platform, path=str(file_path))
        return str(file_path)

    async def save_cookie_file(
        self, platform: str, content_bytes: bytes, uploaded_by_user_id: uuid.UUID
    ) -> tuple[bool, str]:
        """
        Validate and save a new cookie file.
        PERMISSIVE: Saves cookies even if validation test fails, as long as format is correct.
        """
        try:
            content = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return False, "❌ Error: Failed to decode file as UTF-8."

        is_valid_format, error_msg = self._validate_netscape_format(content)
        if not is_valid_format:
            return False, f"❌ Error: Invalid Netscape format: {error_msg}"

        expires_at = self._extract_earliest_expiry(content)
        if expires_at and expires_at < datetime.datetime.now(datetime.timezone.utc):
            return False, f"❌ Error: Cookies in this file are already expired (expired at {expires_at})."

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}.txt"
        save_path = settings.cookies.cookies_dir / platform / filename

        try:
            def _write_file() -> None:
                with open(save_path, "w", encoding="utf-8") as f:
                    f.write(content)
            await asyncio.to_thread(_write_file)
        except Exception as e:
            return False, f"❌ Error: Failed to save to disk: {e}"

        # DB: Deactivate old, add new
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

        # Validation (Informational only)
        test_url = self._get_test_url(platform)
        if test_url:
            is_working, validation_error = await self._test_cookie_file(str(save_path), test_url)
            if not is_working:
                log.warning("cookie_validation_warning", platform=platform, error=validation_error)
                return True, f"✅ Cookies saved and activated!\n\n⚠️ <b>Validation Warning:</b> The test check failed ({validation_error}). They might still work for real downloads, so please try downloading a video now."

        return True, "✅ Cookie file successfully validated and activated."

    async def _test_cookie_file(self, file_path: str, test_url: str) -> tuple[bool, str | None]:
        """Run a non-blocking test of the cookie file."""
        from utils.proxy import proxy_pool
        proxy = await proxy_pool.get_proxy_for_url(test_url)
        proxy_url = proxy.ytdlp_url if proxy else None

        # Find node path
        node_path = shutil.which("node") or "/usr/bin/node"
        if not os.path.exists(node_path):
            node_path = None

        # CLI command format for js-runtimes
        cmd = [
            "yt-dlp",
            "--cookies", file_path,
            "--simulate",
            "--no-warnings",
            "--quiet",
            "--no-check-certificate",
            "--socket-timeout", "10",
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ]
        
        if node_path:
            cmd.extend(["--js-runtimes", f"node:{node_path}"])
        if proxy_url:
            cmd.extend(["--proxy", proxy_url])
        cmd.append(test_url)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(process.communicate(), timeout=20.0)
            except asyncio.TimeoutError:
                try: process.kill()
                except: pass
                return False, "Timeout"

            if process.returncode == 0:
                return True, None

            err = stderr.decode().strip()
            if "No video formats found" in err:
                return True, None 
            return False, err[:100]
        except Exception as e:
            return False, str(e)

    def _validate_netscape_format(self, content: str) -> tuple[bool, str | None]:
        lines = content.strip().splitlines()
        data_lines = 0
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"): continue
            if len(line.split("\t")) == 7: data_lines += 1
        return (True, None) if data_lines > 0 else (False, "No valid cookie lines (7 tab-separated columns required)")

    def _extract_earliest_expiry(self, content: str) -> datetime.datetime | None:
        expiries = []
        for line in content.strip().splitlines():
            if not line.strip() or line.startswith("#"): continue
            f = line.split("\t")
            if len(f) >= 5:
                try:
                    ts = int(f[4])
                    if 0 < ts < 2147483647:
                        expiries.append(datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc))
                except: continue
        return min(expiries) if expiries else None

    def _normalize_domain(self, url: str) -> str:
        d = urlparse(url).netloc.lower()
        return d[4:] if d.startswith("www.") else d

    def _platform_key(self, domain: str) -> str:
        m = {
            "youtube.com": "youtube", "youtu.be": "youtube",
            "tiktok.com": "tiktok",
            "instagram.com": "instagram",
            "reddit.com": "reddit", "redd.it": "reddit",
            "twitter.com": "twitter", "x.com": "twitter",
            "facebook.com": "facebook", "fb.watch": "facebook",
        }
        return m.get(domain, "generic")

    def _get_test_url(self, platform: str) -> str | None:
        u = {"youtube": "https://www.youtube.com/watch?v=jNQXAC9IVRw", "tiktok": "https://www.tiktok.com/@tiktok/video/7346859664673328427"}
        return u.get(platform)

cookie_manager = CookieManager()
