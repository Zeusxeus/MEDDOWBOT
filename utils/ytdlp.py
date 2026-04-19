from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
import yt_dlp  # type: ignore
from yt_dlp.utils import DownloadError  # type: ignore

from utils.cookies import cookie_manager
from utils.proxy import proxy_pool

log = structlog.get_logger(__name__)


class YtDlpError(Exception):
    """Base exception for yt-dlp operations."""


class YtDlpExtractError(YtDlpError):
    """Raised when metadata extraction fails."""


class YtDlpDownloadError(YtDlpError):
    """Raised when download fails."""


class YtDlpFormatError(YtDlpError):
    """Raised when no suitable format is found."""


class YtDlpAuthError(YtDlpError):
    """Raised when authentication/cookies are required or expired."""


@dataclass(frozen=True)
class FormatInfo:
    """Simplified format information from yt-dlp."""

    format_id: str
    ext: str
    resolution: str | None = None
    filesize: int | None = None
    vcodec: str | None = None
    acodec: str | None = None


@dataclass(frozen=True)
class PreflightResult:
    """Result of metadata extraction before download."""

    url: str
    title: str
    thumbnail: str | None
    duration: int | None
    formats: list[FormatInfo]
    platform: str
    user_format_quality: str

    def compute_url_hash(self) -> str:
        """Compute SHA256 of url + user_format_quality."""
        content = f"{self.url}{self.user_format_quality}"
        return hashlib.sha256(content.encode()).hexdigest()


@dataclass(frozen=True)
class DownloadResult:
    """Result of a successful media download."""

    file_path: Path
    filename: str
    size_bytes: int
    duration: int | None
    thumbnail_url: str | None
    platform: str


class YtDlpLogger:
    """Redirects yt-dlp logs to structlog."""

    def debug(self, msg: str) -> None:
        """Filter out common noisy messages if needed."""
        if msg.startswith("[debug] "):
            log.debug("ytdlp_debug", message=msg[8:])
        else:
            log.debug("ytdlp_info", message=msg)

    def warning(self, msg: str) -> None:
        """Log warnings."""
        log.warning("ytdlp_warning", message=msg)

    def error(self, msg: str) -> None:
        """Log errors."""
        log.error("ytdlp_error", message=msg)


def build_format_selector(quality: str, max_size_mb: int | None = None) -> str:
    """
    Constructs the yt-dlp format string.

    Example for '720': bestvideo[height<=720]+bestaudio/best[height<=720]
    """
    if quality == "audio":
        selector = "bestaudio/best"
    else:
        try:
            height = int(quality)
            selector = f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"
        except ValueError:
            selector = "best"

    if max_size_mb:
        # Note: This is a rough filter as yt-dlp's filesize estimation isn't always perfect
        selector = f"({selector})[filesize<{max_size_mb}M]"

    return selector


def select_best_format(formats: list[dict[str, Any]], quality: str) -> FormatInfo | None:
    """Logic to pick the best format given a quality preference."""
    if not formats:
        return None

    video_formats = [f for f in formats if f.get("vcodec") != "none"]

    if quality == "audio":
        audio_formats = [f for f in formats if f.get("vcodec") == "none"]
        if not audio_formats:
            # Fallback to any format if no audio-only found
            audio_formats = formats

        # Sort by abr (average bitrate)
        audio_formats.sort(key=lambda x: x.get("abr") or 0, reverse=True)
        best = audio_formats[0]
    else:
        try:
            target_height = int(quality)
        except ValueError:
            target_height = 1080

        # Filter and sort
        eligible = []
        for f in video_formats:
            height = f.get("height")
            if height is not None and isinstance(height, (int, float)) and height <= target_height:
                eligible.append(f)

        if not eligible:
            # Auto-downgrade: pick the best available if all are above target
            video_formats.sort(key=lambda x: x.get("height") or 0, reverse=True)
            best = video_formats[-1] if video_formats else formats[0]
        else:
            eligible.sort(key=lambda x: (x.get("height") or 0, x.get("tbr") or 0), reverse=True)
            best = eligible[0]

    return FormatInfo(
        format_id=best["format_id"],
        ext=best["ext"],
        resolution=f"{best.get('width')}x{best.get('height')}"
        if best.get("width") and best.get("height")
        else None,
        filesize=best.get("filesize") or best.get("filesize_approx"),
        vcodec=best.get("vcodec"),
        acodec=best.get("acodec"),
    )


async def fetch_metadata(url: str, user_format_quality: str) -> PreflightResult:
    """
    Extracts metadata for a given URL.

    Uses proxy and cookies if available.
    """
    proxy = await proxy_pool.get_proxy_for_url(url)
    cookie_file = await cookie_manager.get_cookie_file(url)

    opts = {
        "quiet": True,
        "no_warnings": True,
        "logger": YtDlpLogger(),
        "skip_download": True,
        "extract_flat": "in_playlist",
        "cookiefile": cookie_file,
        "proxy": proxy.ytdlp_url if proxy else None,
    }

    def _extract() -> dict[str, Any]:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)  # type: ignore

    try:
        # Wrap in to_thread with a timeout (e.g. 30 seconds)
        info = await asyncio.wait_for(asyncio.to_thread(_extract), timeout=30.0)
    except asyncio.TimeoutError:
        raise YtDlpExtractError("Metadata extraction timed out")
    except DownloadError as e:
        msg = str(e).lower()
        if any(term in msg for term in ("login", "sign in", "confirm your age")):
            raise YtDlpAuthError(f"Authentication required: {e}")
        raise YtDlpExtractError(f"Failed to extract metadata: {e}")
    except Exception as e:
        raise YtDlpExtractError(f"Unexpected error during extraction: {e}")

    formats_data: list[dict[str, Any]] = info.get("formats", [])
    formats = []
    for f in formats_data:
        formats.append(
            FormatInfo(
                format_id=f["format_id"],
                ext=f["ext"],
                resolution=f"{f.get('width')}x{f.get('height')}"
                if f.get("width") and f.get("height")
                else None,
                filesize=f.get("filesize") or f.get("filesize_approx"),
                vcodec=f.get("vcodec"),
                acodec=f.get("acodec"),
            )
        )

    return PreflightResult(
        url=url,
        title=info.get("title", "Unknown Title"),
        thumbnail=info.get("thumbnail"),
        duration=info.get("duration"),
        formats=formats,
        platform=info.get("extractor", "generic"),
        user_format_quality=user_format_quality,
    )


async def download_media(
    url: str,
    output_dir: Path,
    format_selector: str,
    job_id: uuid.UUID,
    progress_callback: Callable[[dict[str, Any]], Any],
) -> DownloadResult:
    """Downloads media from a URL using yt-dlp."""
    proxy = await proxy_pool.get_proxy_for_url(url)
    cookie_file = await cookie_manager.get_cookie_file(url)

    loop = asyncio.get_event_loop()

    def progress_hook(d: dict[str, Any]) -> None:
        """Call the async progress_callback from the thread-safe way."""
        loop.call_soon_threadsafe(progress_callback, d)

    opts = {
        "format": format_selector,
        "outtmpl": str(output_dir / f"{job_id}.%(ext)s"),
        "logger": YtDlpLogger(),
        "noprogress": True,
        "cookiefile": cookie_file,
        "proxy": proxy.ytdlp_url if proxy else None,
        "progress_hooks": [progress_hook],
    }

    start_time = loop.time()
    success = False

    try:

        def _download() -> dict[str, Any]:
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=True)  # type: ignore

        info = await asyncio.to_thread(_download)
        success = True

        # Construct result
        ext = info.get("ext", "mp4")
        file_path = output_dir / f"{job_id}.{ext}"

        # Sometimes yt-dlp merges files and the extension changes or it might be different
        # Better to check what was actually downloaded
        actual_files = list(output_dir.glob(f"{job_id}.*"))
        if actual_files:
            file_path = actual_files[0]

        return DownloadResult(
            file_path=file_path,
            filename=info.get("title", str(job_id)),
            size_bytes=file_path.stat().st_size if file_path.exists() else 0,
            duration=info.get("duration"),
            thumbnail_url=info.get("thumbnail"),
            platform=info.get("extractor", "generic"),
        )

    except DownloadError as e:
        msg = str(e).lower()
        if any(term in msg for term in ("login", "sign in", "confirm your age")):
            raise YtDlpAuthError(f"Authentication required: {e}")
        raise YtDlpDownloadError(f"Download failed: {e}")
    except Exception as e:
        raise YtDlpDownloadError(f"Unexpected error during download: {e}")
    finally:
        if proxy:
            latency = (loop.time() - start_time) * 1000
            if success:
                await proxy_pool.record_proxy_success(proxy.id, latency)
            else:
                await proxy_pool.record_proxy_failure(proxy.id)
