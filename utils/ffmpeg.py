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
    Detect available hardware encoder.

    Returns:
        "h264_nvenc", "h264_vaapi", or None.
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

        if "h264_nvenc" in output:
            return "h264_nvenc"
        if "h264_vaapi" in output:
            return "h264_vaapi"
    except Exception as e:
        log.warning("failed_to_detect_hw_encoder", error=str(e))

    return None


async def get_duration(path: Path) -> float:
    """
    Uses ffprobe to get duration in seconds.

    Args:
        path: Path to the video file.

    Returns:
        Duration in seconds.

    Raises:
        FFmpegError: If ffprobe fails.
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

    Args:
        path: Path to the file.
        max_bytes: Maximum size in bytes.
    """
    return path.stat().st_size > max_bytes


async def hw_encode(path: Path, encoder: str, target_mb: int) -> Path:
    """
    Implements HW accelerated encoding.

    Args:
        path: Path to the input video.
        encoder: The hardware encoder to use.
        target_mb: Target size in MB.

    Returns:
        Path to the compressed video.

    Raises:
        FFmpegError: If encoding fails.
    """
    duration = await get_duration(path)
    target_bytes = target_mb * 1024 * 1024
    bitrate = int((target_bytes * 8) / duration * 0.9)

    output_path = path.with_suffix(f".hw{path.suffix}")

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

    log.info("starting_hw_encode", path=str(path), encoder=encoder, target_mb=target_mb)

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
    Orchestrates compression. Tries HW encoder first, falls back to two-pass libx264.

    Args:
        path: Path to the input video.
        target_mb: Target size in MB.

    Returns:
        Path to the compressed video.

    Raises:
        FFmpegError: If compression fails.
    """
    encoder = await detect_hw_encoder()
    if encoder:
        try:
            return await hw_encode(path, encoder, target_mb)
        except FFmpegError as e:
            log.warning("hw_encode_failed_falling_back", error=str(e))

    # Two-pass logic
    duration = await get_duration(path)
    target_bytes = target_mb * 1024 * 1024
    bitrate = int((target_bytes * 8) / duration * 0.9)

    # Pass 1
    pass1_cmd = [
        settings.ffmpeg.binary_path,
        "-y",
        "-i",
        str(path),
        "-c:v",
        "libx264",
        "-b:v",
        str(bitrate),
        "-pass",
        "1",
        "-an",
        "-f",
        "null",
        "/dev/null",
    ]

    output_path = path.with_suffix(".mp4")
    if output_path == path:
        output_path = path.with_name(f"compressed_{path.name}")
        if not output_path.name.endswith(".mp4"):
            output_path = output_path.with_suffix(".mp4")
            
    pass2_cmd = [
        settings.ffmpeg.binary_path,
        "-y",
        "-i",
        str(path),
        "-c:v",
        "libx264",
        "-b:v",
        str(bitrate),
        "-pass",
        "2",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(output_path),
    ]

    log.info("starting_two_pass_compress", path=str(path), target_mb=target_mb)

    try:
        p1 = await asyncio.create_subprocess_exec(
            *pass1_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr1 = await p1.communicate()
        if p1.returncode != 0:
            raise FFmpegError(f"Pass 1 failed: {stderr1.decode()}")

        p2 = await asyncio.create_subprocess_exec(
            *pass2_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr2 = await p2.communicate()

        if p2.returncode != 0:
            raise FFmpegError(f"Pass 2 failed: {stderr2.decode()}")

        return output_path
    finally:
        # Cleanup ffmpeg2pass files
        for f in Path(".").glob("ffmpeg2pass-0.*"):
            f.unlink(missing_ok=True)


async def split_video(path: Path, max_mb: int) -> list[Path]:
    """
    Splits video if it remains over the limit.

    Args:
        path: Path to the video file.
        max_mb: Maximum size of each part in MB.

    Returns:
        List of Paths to the split parts.

    Raises:
        FFmpegError: If splitting fails.
    """
    duration = await get_duration(path)
    size = path.stat().st_size
    num_parts = math.ceil(size / (max_mb * 1024 * 1024))

    if num_parts <= 1:
        return [path]

    part_duration = duration / num_parts
    output_pattern = path.with_name(f"{path.stem}_part%03d{path.suffix}")

    cmd = [
        settings.ffmpeg.binary_path,
        "-y",
        "-i",
        str(path),
        "-f",
        "segment",
        "-segment_time",
        str(part_duration),
        "-c",
        "copy",
        str(output_pattern),
    ]

    log.info("splitting_video", path=str(path), num_parts=num_parts)

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()

    if process.returncode != 0:
        raise FFmpegError(f"Split failed: {stderr.decode()}")

    # Find the created parts
    parts = sorted(list(path.parent.glob(f"{path.stem}_part*{path.suffix}")))
    if not parts:
        log.warning("no_split_parts_found", path=str(path))
        return [path]
    return parts
