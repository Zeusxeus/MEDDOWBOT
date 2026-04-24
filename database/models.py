from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


# ─────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────


class JobStatus(str, enum.Enum):
    """Status of a download job."""

    PENDING = "pending"  # Enqueued, not started
    RUNNING = "running"  # Worker claimed it
    DONE = "done"  # Uploaded to Telegram
    FAILED = "failed"  # Exhausted all retries
    CANCELLED = "cancelled"  # User cancelled via /cancel


class ProxyStatus(str, enum.Enum):
    """Status of a proxy."""

    ACTIVE = "active"  # Passing health checks, in rotation
    DEAD = "dead"  # Failed max_consecutive_failures checks
    DISABLED = "disabled"  # Admin manually disabled
    TESTING = "testing"  # Currently being health-checked


class ProxyRotationStrategy(str, enum.Enum):
    """Proxy rotation strategies."""

    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    LEAST_USED = "least_used"
    LEAST_ERRORS = "least_errors"


# ─────────────────────────────────────────────
# USER
# ─────────────────────────────────────────────


class User(Base):
    """
    Every Telegram user who interacts with the bot.
    Created on first message via AuthMiddleware.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    # telegram_id is unique per user across Telegram, never changes

    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Can be None if user has no @username

    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # is_admin = True for users in BOT__ADMIN_IDS OR promoted via /admin promote

    rate_limit_override: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # None = use global setting. Integer = override for this user.
    # Admin can set this to 0 (ban from rate limit perspective) or 100 (VIP)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Updated by AuthMiddleware on every message

    total_downloads: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_bytes_served: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    # Denormalized counters — updated when jobs complete. Avoids COUNT() queries for /stats

    # Relationships
    settings: Mapped[Optional["UserSettings"]] = relationship(
        back_populates="user", uselist=False, lazy="selectin"
    )
    jobs: Mapped[list["DownloadJob"]] = relationship(back_populates="user", lazy="select")

    def __repr__(self) -> str:
        return f"<User telegram_id={self.telegram_id} username={self.username}>"


# ─────────────────────────────────────────────
# USER SETTINGS
# ─────────────────────────────────────────────


class UserSettings(Base):
    """
    Per-user preferences. One row per user (1:1 with User).
    Created with defaults on first /settings access or first download.
    """

    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Primary key = FK. Enforces 1:1 relationship at DB level.

    # Video quality preference
    # "best" = highest quality yt-dlp selects
    # "1080", "720", "480", "360" = max resolution
    # "audio" = audio-only (mp3/m4a)
    format_quality: Mapped[str] = mapped_column(String(10), default="720", nullable=False)

    # Whether to compress videos that exceed 49MB
    # If False AND Local Bot API disabled: large files will be sent as document if possible
    compression_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Bundle multiple files into a .zip (for Reddit bulk downloads)
    zip_files: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Show progress updates while downloading
    # False = only notify on completion
    show_progress: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Preferred language for the bot interface
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)

    # Max file size in MB
    max_file_size: Mapped[int] = mapped_column(Integer, default=50, nullable=False)

    # Whether to upload videos as video media or documents
    upload_as_video: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="settings")

    def __repr__(self) -> str:
        return f"<UserSettings user_id={self.user_id} format={self.format_quality}>"


# ─────────────────────────────────────────────
# DOWNLOAD JOB
# ─────────────────────────────────────────────


class DownloadJob(Base):
    """
    Every download request creates one row.
    This is the source of truth for job state.
    Taskiq provides durability; this provides queryability.
    """

    __tablename__ = "download_jobs"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # The URL exactly as received from the user
    url: Mapped[str] = mapped_column(Text, nullable=False)

    # SHA256(url + format_quality) — used for content-aware caching
    # If two users request same URL+format, second gets cached result instantly
    url_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    # Telegram file_id of the uploaded file
    # Set when status=DONE. Used for instant cache delivery on future requests.
    # file_id is permanent and can be forwarded/re-sent at zero cost.
    telegram_file_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), default=JobStatus.PENDING, nullable=False, index=True
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 0–100, updated by worker via Redis pub/sub

    # ── Worker tracking ──
    claimed_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Worker instance ID that claimed this job. e.g. "worker-3-pid-12345"
    # Used for stale job detection on startup.

    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Worker updates this every 30s. If > 5min old and status=RUNNING → job is stale.

    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    taskiq_task_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Taskiq task ID for status checking

    # ── Result info ──
    filename: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    platform: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # e.g. "youtube", "instagram", "twitter"

    format_requested: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    # What the user requested (copied from UserSettings at job creation time)
    # Stored here so settings changes don't affect in-flight jobs

    # ── Proxy tracking ──
    proxy_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("proxies.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Which proxy was used. NULL = no proxy (direct connection).

    # ── Error info ──
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # e.g. "yt_dlp.DownloadError", "FFmpegError", "TelegramError"

    # ── Timestamps ──
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="jobs")
    proxy: Mapped[Optional["Proxy"]] = relationship(back_populates="jobs")

    __table_args__ = (
        # Fast lookup for /history command (user's jobs, newest first)
        Index("ix_jobs_user_created", "user_id", "created_at"),
        # Fast lookup for stale job recovery
        Index("ix_jobs_status_heartbeat", "status", "heartbeat_at"),
        # Fast cache lookup (skip download if same URL+format completed recently)
        Index("ix_jobs_url_hash_status", "url_hash", "status"),
    )

    def __repr__(self) -> str:
        return f"<DownloadJob id={self.id} status={self.status} user={self.user_id}>"


# ─────────────────────────────────────────────
# PROXY
# ─────────────────────────────────────────────


class Proxy(Base):
    """
    Residential proxy pool for yt-dlp routing.
    """

    __tablename__ = "proxies"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # ── Connection details ──
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    # Note: Password stored plaintext in DB. Use DB encryption at rest in high-security envs.

    label: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Optional human-readable label, e.g. "US-West-1", "residential-pool-A"

    # ── Status ──
    status: Mapped[ProxyStatus] = mapped_column(
        Enum(ProxyStatus), default=ProxyStatus.ACTIVE, nullable=False, index=True
    )

    # ── Health tracking ──
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_success_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_successes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_latency_ms: Mapped[Optional[float]] = mapped_column(nullable=True)
    # Running average latency from health checks

    # ── Usage tracking (for rotation strategies) ──
    total_uses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Used for round_robin (order by last_used_at ASC) and least_used (order by total_uses ASC)

    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    added_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    jobs: Mapped[list["DownloadJob"]] = relationship(back_populates="proxy")

    __table_args__ = (
        # Prevent duplicate proxies
        UniqueConstraint("host", "port", "username", name="uq_proxy_endpoint"),
    )

    @property
    def ytdlp_url(self) -> str:
        """Convert stored format to yt-dlp proxy URL format."""
        return f"http://{self.username}:{self.password}@{self.host}:{self.port}"

    @property
    def display_str(self) -> str:
        """Safe display string (hides password)."""
        return f"{self.host}:{self.port}:{self.username}:***"

    @classmethod
    def from_string(cls, proxy_string: str) -> "Proxy":
        """Parse proxy string in format: host:port:username:password"""
        parts = proxy_string.strip().split(":")
        if len(parts) != 4:
            raise ValueError(
                f"Invalid proxy format. Expected host:port:username:password, got: {proxy_string!r}"
            )
        host, port_str, username, password = parts
        try:
            port = int(port_str)
        except ValueError:
            raise ValueError(f"Invalid port: {port_str!r}. Must be an integer.")
        if not (1 <= port <= 65535):
            raise ValueError(f"Port {port} out of range (1-65535)")
        return cls(host=host, port=port, username=username, password=password)

    def __repr__(self) -> str:
        return f"<Proxy {self.host}:{self.port} status={self.status}>"


# ─────────────────────────────────────────────
# COOKIE FILE
# ─────────────────────────────────────────────


class CookieFile(Base):
    """
    Tracks uploaded cookie files for platform authentication.
    """

    __tablename__ = "cookie_files"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    platform: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # e.g. "youtube", "instagram" — matches yt-dlp extractor name

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # Filename on disk (relative to COOKIES__COOKIES_DIR)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Only one active cookie file per platform at a time.

    # ── Validation state ──
    last_validated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_valid: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    # None = not yet validated, True = working, False = expired/invalid

    validation_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Metadata ──
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    uploaded_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_cookies_platform_active", "platform", "is_active"),)

    @property
    def file_path(self) -> str:
        from config.settings import settings

        return str(settings.cookies.cookies_dir / self.platform / self.filename)

    def __repr__(self) -> str:
        return f"<CookieFile platform={self.platform} active={self.is_active}>"


# ─────────────────────────────────────────────
# RATE LIMIT LOG (analytics only)
# ─────────────────────────────────────────────


class RateLimitLog(Base):
    """
    Analytics table — NOT used for live rate limiting.
    Live rate limiting uses Redis Lua token bucket.
    """

    __tablename__ = "rate_limit_logs"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_ratelimit_user_occurred", "user_id", "occurred_at"),)
