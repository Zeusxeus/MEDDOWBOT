from __future__ import annotations

import asyncio
import math
from pathlib import Path

import structlog

from config.settings import settings

log = structlog.get_logger(__name__)


class FFmpegError(Exception):
    """Base exception for FFmpeg operations."""


async def detect_hw_encoder() -> str | None:
    """
    Detect available hardware encoder for HEVC (H.265).

    Returns:
        "hevc_nvenc", "hevc_vaapi", or None.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            settings.ffmpeg.binary_path,
            "-encoders",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        output = stdout.decode().lower()

        if "hevc_nvenc" in output:
            return "hevc_nvenc"
        if "hevc_vaapi" in output:
            return "hevc_vaapi"
    except Exception as e:
        log.warning("failed_to_detect_hw_encoder", error=str(e))

    return None


async def get_duration(path: Path) -> float:
    """
    Uses ffprobe to get duration in seconds.
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise FFmpegError(f"ffprobe failed: {stderr.decode()}")
        return float(stdout.decode().strip())
    except Exception as e:
        log.error("failed_to_get_duration", path=str(path), error=str(e))
        if isinstance(e, FFmpegError):
            raise
        raise FFmpegError(f"Failed to get duration: {e}") from e


def needs_compression(path: Path, max_bytes: int) -> bool:
    """
    Returns True if file size > max_bytes.
    """
    return path.stat().st_size > max_bytes


async def hw_encode(path: Path, encoder: str, target_mb: int) -> Path:
    """
    Implements HEVC HW accelerated encoding.
    """
    duration = await get_duration(path)
    target_bytes = target_mb * 1024 * 1024
    bitrate = int((target_bytes * 8) / duration * 0.9)

    output_path = path.with_suffix(".mp4")
    if output_path == path:
        output_path = path.with_name(f"compressed_{path.name}").with_suffix(".mp4")

    cmd = [
        settings.ffmpeg.binary_path,
        "-y",
        "-i",
        str(path),
        "-c:v",
        encoder,
        "-b:v",
        str(bitrate),
        "-maxrate",
        str(int(bitrate * 1.5)),
        "-bufsize",
        str(bitrate * 2),
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(output_path),
    ]

    log.info("starting_hevc_hw_encode", path=str(path), encoder=encoder, target_mb=target_mb)

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()

    if process.returncode != 0:
        log.error("hw_encode_failed", stderr=stderr.decode())
        raise FFmpegError(f"HW encode failed: {stderr.decode()}")

    return output_path


async def compress_video(path: Path, target_mb: int) -> Path:
    """
    Orchestrates compression using HEVC (H.265).
    """
    encoder = await detect_hw_encoder()
    if encoder:
        try:
            return await hw_encode(path, encoder, target_mb)
        except FFmpegError as e:
            log.warning("hw_encode_failed_falling_back", error=str(e))

    # Fallback to libx265 (HEVC)
    duration = await get_duration(path)
    target_bytes = target_mb * 1024 * 1024
    bitrate = int((target_bytes * 8) / duration * 0.9)

    output_path = path.with_suffix(".mp4")
    if output_path == path:
        output_path = path.with_name(f"compressed_{path.name}").with_suffix(".mp4")

    # Two-pass HEVC
    # Pass 1
    pass1_cmd = [
        settings.ffmpeg.binary_path,
        "-y",
        "-i",
        str(path),
        "-c:v",
        "libx265",
        "-b:v",
        str(bitrate),
        "-x265-params", "pass=1",
        "-an",
        "-f",
        "null",
        "/dev/null",
    ]

    # Pass 2
    pass2_cmd = [
        settings.ffmpeg.binary_path,
        "-y",
        "-i",
        str(path),
        "-c:v",
        "libx265",
        "-b:v",
        str(bitrate),
        "-x265-params", "pass=2",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(output_path),
    ]

    log.info("starting_hevc_two_pass_compress", path=str(path), target_mb=target_mb)

    try:
        p1 = await asyncio.create_subprocess_exec(
            *pass1_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr1 = await p1.communicate()
        if p1.returncode != 0:
            # If libx265 is not available, you might need to install it. 
            # But we assume the environment has it.
            raise FFmpegError(f"Pass 1 failed: {stderr1.decode()}")

        p2 = await asyncio.create_subprocess_exec(
            *pass2_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr2 = await p2.communicate()

        if p2.returncode != 0:
            raise FFmpegError(f"Pass 2 failed: {stderr2.decode()}")

        return output_path
    finally:
        # Cleanup x265 pass files
        for f in Path(".").glob("x265_2pass.log*"):
            f.unlink(missing_ok=True)
