from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import time
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


def get_format_selector(url: str, quality: str) -> str:
    """
    Determines the yt-dlp format selector based on platform and quality.
    """
    if quality == "audio":
        return "bestaudio/best"

    url_lower = url.lower()
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"

    if any(
        p in url_lower for p in ["tiktok.com", "instagram.com", "twitter.com", "x.com", "reddit.com"]
    ):
        return "best[ext=mp4]/best"

    return "best[ext=mp4]/best"


def select_best_format(formats: list[FormatInfo], quality: str) -> FormatInfo | None:
    """
    From available formats, pick the best one under FFMPEG__MAX_SIZE_MB.
    """
    from config.settings import settings

    max_bytes = settings.ffmpeg.max_size_mb * 1024 * 1024
    quality_order = ["1080", "720", "480", "360"]

    if quality == "audio":
        audio_formats = [f for f in formats if f.vcodec == "none" or f.vcodec is None]
        if not audio_formats:
            return None
        return sorted(audio_formats, key=lambda f: f.filesize or 0, reverse=True)[0]

    if quality == "best":
        video_formats = [f for f in formats if f.vcodec != "none"]
        if not video_formats:
            return None
        return sorted(video_formats, key=lambda f: f.filesize or 0, reverse=True)[0]

    if quality not in quality_order:
        return None

    try:
        start_idx = quality_order.index(quality)
    except ValueError:
        start_idx = 1

    for q in quality_order[start_idx:]:
        height = int(q)
        candidates = []
        for f in formats:
            if f.vcodec == "none":
                continue
            
            f_height = 0
            if f.resolution and "x" in f.resolution:
                try:
                    f_height = int(f.resolution.split("x")[1])
                except (ValueError, IndexError):
                    continue
            
            if f_height <= height and (f.filesize is None or f.filesize <= max_bytes):
                candidates.append(f)

        if candidates:
            return sorted(
                candidates,
                key=lambda f: (
                    int(f.resolution.split("x")[1]) if f.resolution and "x" in f.resolution else 0,
                    f.filesize or 0,
                ),
                reverse=True,
            )[0]

    return None


def build_ydl_opts(
    url: str,
    format_selector: str,
    proxy_url: str | None,
    cookie_file: str | None,
    job_id: uuid.UUID | str,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """
    Builds the options dictionary for YoutubeDL.
    """

    def hook_fn(d: dict[str, Any]) -> None:
        if progress_callback:
            try:
                progress_callback(d)
            except Exception as e:
                log.error("progress_callback_error", error=str(e), job_id=str(job_id))

    # Find node path
    node_path = shutil.which("node") or "/usr/bin/node"
    if not os.path.exists(node_path):
        node_path = None
    
    if node_path:
        log.debug("js_runtime_found", path=node_path)
    else:
        log.warning("js_runtime_not_found")

    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": False,
        "extract_flat": False,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "http_chunk_size": 10485760,  # 10MB
        "proxy": proxy_url,
        "cookiefile": cookie_file,
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
        "check_formats": False,
        "extractor_args": {
            "youtube": {
                "player_client": ["ios"],
                "player_skip": ["webpage", "configs"],
            }
        },
    }
    
    # Python API expects a dict for js_runtimes if providing configuration
    if node_path:
        opts["js_runtimes"] = {"node": {"path": node_path}}
    
    if progress_callback:
        opts["progress_hooks"] = [hook_fn]

    return opts


async def fetch_metadata(url: str, user_format_quality: str) -> PreflightResult:
    """
    Extracts metadata for a given URL using yt-dlp.
    """
    proxy = await proxy_pool.get_proxy_for_url(url)
    proxy_url = proxy.ytdlp_url if proxy else None
    cookie_file = await cookie_manager.get_cookie_file(url)
    if cookie_file:
        log.debug("using_cookie_file", path=cookie_file, url=url)

    format_selector = get_format_selector(url, user_format_quality)
    opts = build_ydl_opts(url, format_selector, proxy_url, cookie_file, "metadata")
    opts["skip_download"] = True

    def _extract() -> dict[str, Any]:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)  # type: ignore

    start_time = time.perf_counter()
    try:
        info = await asyncio.to_thread(_extract)
        if proxy:
            latency = (time.perf_counter() - start_time) * 1000
            await proxy_pool.record_proxy_success(proxy.id, latency)
    except DownloadError as e:
        if proxy:
            await proxy_pool.record_proxy_failure(proxy.id)
        msg = str(e)
        msg_lower = msg.lower()
        log.warning("ytdlp_extract_error", url=url, error=msg)
        
        if any(kw in msg_lower for kw in ["sign in", "login", "confirm your age", "account is private"]):
            raise YtDlpAuthError(f"Authentication required or content private: {msg}") from e
            
        if "10204" in msg or "video not available" in msg_lower:
            raise YtDlpExtractError(f"Video is unavailable: {msg}") from e

        raise YtDlpExtractError(msg) from e
    except Exception as e:
        if proxy:
            await proxy_pool.record_proxy_failure(proxy.id)
        log.exception("metadata_extraction_failed", url=url, error=str(e))
        raise YtDlpExtractError(str(e)) from e

    formats_data: list[dict[str, Any]] = info.get("formats", [])
    formats = [
        FormatInfo(
            format_id=f.get("format_id", "unknown"),
            ext=f.get("ext", "unknown"),
            resolution=f"{f.get('width')}x{f.get('height')}"
            if f.get("width") and f.get("height")
            else None,
            filesize=f.get("filesize") or f.get("filesize_approx"),
            vcodec=f.get("vcodec"),
            acodec=f.get("acodec"),
        )
        for f in formats_data
    ]

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
    progress_callback: Callable[[dict[str, Any]], None],
) -> DownloadResult:
    """
    Downloads media from a URL using yt-dlp.
    """
    proxy = await proxy_pool.get_proxy_for_url(url)
    proxy_url = proxy.ytdlp_url if proxy else None
    cookie_file = await cookie_manager.get_cookie_file(url)
    if cookie_file:
        log.debug("using_cookie_file", path=cookie_file, url=url)

    loop = asyncio.get_running_loop()

    def wrapped_callback(d: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(progress_callback, d)

    opts = build_ydl_opts(url, format_selector, proxy_url, cookie_file, job_id, wrapped_callback)
    opts.update(
        {
            "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
            "format": format_selector,
            "merge_output_format": "mp4",
            "postprocessors": [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}],
        }
    )

    def _download() -> dict[str, Any]:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=True)  # type: ignore

    start_time = time.perf_counter()
    try:
        info = await asyncio.to_thread(_download)
        if proxy:
            latency = (time.perf_counter() - start_time) * 1000
            await proxy_pool.record_proxy_success(proxy.id, latency)
    except DownloadError as e:
        if proxy:
            await proxy_pool.record_proxy_failure(proxy.id)
        msg = str(e)
        msg_lower = msg.lower()
        log.warning("ytdlp_download_error", url=url, job_id=str(job_id), error=msg)
        
        if any(kw in msg_lower for kw in ["sign in", "login", "confirm your age"]):
            raise YtDlpAuthError(msg) from e
        raise YtDlpDownloadError(msg) from e
    except Exception as e:
        if proxy:
            await proxy_pool.record_proxy_failure(proxy.id)
        log.exception("download_failed", url=url, job_id=str(job_id), error=str(e))
        raise YtDlpDownloadError(str(e)) from e

    filename = info.get("_filename")
    if not filename:
        files = list(output_dir.glob("*"))
        if not files:
            raise YtDlpDownloadError("Downloaded file not found on disk")
        file_path = files[0]
    else:
        file_path = Path(filename)

    if not file_path.exists():
        mp4_path = file_path.with_suffix(".mp4")
        if mp4_path.exists():
            file_path = mp4_path
        else:
            files = list(output_dir.glob("*"))
            if files:
                file_path = files[0]
            else:
                raise YtDlpDownloadError(f"File not found: {file_path}")

    return DownloadResult(
        file_path=file_path,
        filename=file_path.name,
        size_bytes=file_path.stat().st_size,
        duration=info.get("duration"),
        thumbnail_url=info.get("thumbnail"),
        platform=info.get("extractor", "generic"),
    )
