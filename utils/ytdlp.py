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
    height: int | None = None


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
        content = f"{self.url}:{self.user_format_quality}"
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
    is_youtube = "youtube.com" in url_lower or "youtu.be" in url_lower

    if is_youtube:
        if quality == "best":
            return "bestvideo+bestaudio/best"
        
        try:
            h = int(quality)
        except ValueError:
            h = 720
        
        # Use more flexible selector for YouTube that still targets resolution
        return f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/best[height<={h}][ext=mp4]/best[height<={h}]/best"

    if quality == "best":
        return "best"
    
    try:
        h = int(quality)
        return f"best[height<={h}]/best"
    except ValueError:
        return "best"


def select_best_format(formats: list[FormatInfo], quality: str) -> FormatInfo | None:
    """
    From available formats, pick the best one under FFMPEG__MAX_SIZE_MB.
    """
    from config.settings import settings

    max_bytes = settings.ffmpeg.max_size_mb * 1024 * 1024
    
    if quality == "audio":
        audio_formats = [f for f in formats if f.vcodec == "none" or f.vcodec is None]
        if not audio_formats:
            return sorted(formats, key=lambda f: f.filesize or 0, reverse=True)[0]
        return sorted(audio_formats, key=lambda f: f.filesize or 0, reverse=True)[0]

    if quality == "best":
        video_formats = [f for f in formats if f.vcodec != "none"]
        if not video_formats:
            return sorted(formats, key=lambda f: f.filesize or 0, reverse=True)[0]
        return sorted(video_formats, key=lambda f: f.filesize or 0, reverse=True)[0]

    try:
        target_height = int(quality)
    except ValueError:
        target_height = 720

    # Filter by height and size
    candidates = []
    for f in formats:
        if f.vcodec == "none":
            continue
        
        h = f.height or 0
        if h <= target_height and (f.filesize is None or f.filesize <= max_bytes):
            candidates.append(f)

    if candidates:
        # Sort by height then size
        return sorted(candidates, key=lambda f: (f.height or 0, f.filesize or 0), reverse=True)[0]

    if formats:
        return sorted(formats, key=lambda f: f.filesize or 0, reverse=True)[0]
        
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

    node_path = shutil.which("node") or "/usr/bin/node"
    if not os.path.exists(node_path):
        node_path = None

    is_youtube = "youtube.com" in url.lower() or "youtu.be" in url.lower()
    actual_cookie_file = cookie_file if is_youtube else None
    
    # ADVANCED CLIENT STRATEGY: Use TV and WebCreator to bypass PO Token requirement
    # These clients are currently the best for data-center IPs (VPS)
    clients = ["tv", "web", "web_creator", "mweb"]

    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": False,
        "extract_flat": False,
        "socket_timeout": 60,
        "retries": 5,
        "fragment_retries": 15,
        "http_chunk_size": 10485760,
        "proxy": proxy_url,
        "cookiefile": actual_cookie_file,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "check_formats": False,
        "extractor_args": {
            "youtube": {
                "player_client": ["tv", "web", "web_creator", "mweb", "android"],
                "player_skip": ["configs"],
                "include_dash_manifest": True,
                "include_hls_manifest": True,
            }
        },
        "format": "bestvideo+bestaudio/best",
    }
    
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

    format_selector = get_format_selector(url, user_format_quality)
    opts = build_ydl_opts(url, format_selector, proxy_url, cookie_file, "metadata")
    opts["skip_download"] = True

    async def _try_extract(current_opts: dict[str, Any]) -> dict[str, Any]:
        def __extract() -> dict[str, Any]:
            with yt_dlp.YoutubeDL(current_opts) as ydl:
                return ydl.extract_info(url, download=False)  # type: ignore
        return await asyncio.to_thread(__extract)

    try:
        try:
            info = await _try_extract(opts)
        except (DownloadError, YtDlpAuthError) as e:
            if opts.get("cookiefile"):
                log.warning("cookie_extraction_failed_trying_without_cookies", url=url)
                fallback_opts = opts.copy()
                fallback_opts["cookiefile"] = None
                info = await _try_extract(fallback_opts)
            else:
                raise e

        if proxy:
            await proxy_pool.record_proxy_success(proxy.id, 100)
            
    except DownloadError as e:
        if proxy:
            await proxy_pool.record_proxy_failure(proxy.id)
        msg = str(e)
        log.warning("ytdlp_extract_error", url=url, error=msg)
        if any(kw in msg.lower() for kw in ["sign in", "login", "confirm your age"]):
            raise YtDlpAuthError(f"Authentication required: {msg}") from e
        raise YtDlpExtractError(msg) from e
    except Exception as e:
        if proxy:
            await proxy_pool.record_proxy_failure(proxy.id)
        log.exception("metadata_extraction_failed", url=url, error=str(e))
        raise YtDlpExtractError(str(e)) from e

    formats_data: list[dict[str, Any]] = info.get("formats", [])
    formats = []
    for f in formats_data:
        height = f.get("height")
        if height is None and f.get("resolution"):
            res = f.get("resolution")
            if "x" in res:
                try: height = int(res.split("x")[1])
                except: pass
        
        formats.append(FormatInfo(
            format_id=f.get("format_id", "unknown"),
            ext=f.get("ext", "unknown"),
            resolution=f"{f.get('width')}x{f.get('height')}" if f.get("width") and f.get("height") else f.get("resolution"),
            filesize=f.get("filesize") or f.get("filesize_approx"),
            vcodec=f.get("vcodec"),
            acodec=f.get("acodec"),
            height=height
        ))

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

    loop = asyncio.get_running_loop()
    def wrapped_callback(d: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(progress_callback, d)

    opts = build_ydl_opts(url, format_selector, proxy_url, cookie_file, job_id, wrapped_callback)
    
    if format_selector == "bestaudio/best":
        opts.update({
            "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
            "format": format_selector,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        })
    else:
        opts.update({
            "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
            "format": format_selector,
            "merge_output_format": "mp4",
            "postprocessors": [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}],
        })

    async def _try_download(current_opts: dict[str, Any]) -> dict[str, Any]:
        def __download() -> dict[str, Any]:
            with yt_dlp.YoutubeDL(current_opts) as ydl:
                return ydl.extract_info(url, download=True)
        return await asyncio.to_thread(__download)

    try:
        try:
            info = await _try_download(opts)
        except (DownloadError, YtDlpAuthError) as e:
            if opts.get("cookiefile"):
                log.warning("cookie_download_failed_trying_without_cookies", url=url)
                fallback_opts = opts.copy()
                fallback_opts["cookiefile"] = None
                info = await _try_download(fallback_opts)
            else:
                raise e

        if proxy:
            await proxy_pool.record_proxy_success(proxy.id, 100)
            
    except DownloadError as e:
        if proxy: await proxy_pool.record_proxy_failure(proxy.id)
        msg = str(e)
        if any(kw in msg.lower() for kw in ["sign in", "login", "confirm your age"]):
            raise YtDlpAuthError(msg) from e
        raise YtDlpDownloadError(msg) from e
    except Exception as e:
        if proxy: await proxy_pool.record_proxy_failure(proxy.id)
        raise YtDlpDownloadError(str(e)) from e

    filename = info.get("_filename")
    if not filename:
        files = list(output_dir.glob("*"))
        if not files: raise YtDlpDownloadError("Downloaded file not found")
        file_path = files[0]
    else:
        file_path = Path(filename)

    if not file_path.exists():
        for ext in [".mp4", ".mp3", ".mkv"]:
            p = file_path.with_suffix(ext)
            if p.exists():
                file_path = p
                break
        else:
            files = list(output_dir.glob("*"))
            if files: file_path = files[0]
            else: raise YtDlpDownloadError(f"File not found: {file_path}")

    return DownloadResult(
        file_path=file_path,
        filename=file_path.name,
        size_bytes=file_path.stat().st_size,
        duration=info.get("duration"),
        thumbnail_url=info.get("thumbnail"),
        platform=info.get("extractor", "generic"),
    )
