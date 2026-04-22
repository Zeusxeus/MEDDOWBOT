from __future__ import annotations

import pathlib
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseModel):
    """Telegram bot settings."""
    token: str
    admin_ids: list[int] = Field(default_factory=list)
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: Any) -> list[int]:
        if isinstance(v, str):
            if not v.strip() or v.startswith("your_"):
                return []
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v


class LocalApiSettings(BaseModel):
    """Local Telegram Bot API settings."""
    enabled: bool = False
    url: str = "http://localhost:8081"
    api_id: str | None = None
    api_hash: str | None = None
    working_dir: pathlib.Path = pathlib.Path("/tmp/telegram-bot-api")


class DatabaseSettings(BaseModel):
    """Database connection settings."""
    url: str
    echo: bool = False
    pool_size: int = 10
    max_overflow: int = 20


class RedisSettings(BaseModel):
    """Redis connection settings."""
    url: str = "redis://localhost:6379/0"
    fsm_prefix: str = "bot_fsm"
    cache_prefix: str = "bot_cache"
    pool_size: int = 100


class WorkerSettings(BaseModel):
    """Taskiq worker settings."""
    concurrency: int = 3
    prefetch: int = 1


class RateLimitSettings(BaseModel):
    """User rate limit settings."""
    requests_per_minute: int = 10
    burst: int = 3
    max_concurrent_jobs: int = 2


class DiskSettings(BaseModel):
    """Storage and disk usage settings."""
    downloads_path: pathlib.Path = pathlib.Path("data/downloads")
    temp_path: pathlib.Path = pathlib.Path("data/temp")
    max_disk_usage_gb: float = 10.0
    min_free_gb: float = 2.0


class FFmpegSettings(BaseModel):
    """FFmpeg compression settings."""
    binary_path: str = "ffmpeg"
    threads: int = 0
    target_mb: int = 45
    max_size_mb: int = 49
    large_file_warn_mb: int = 200


class ProxySettings(BaseModel):
    """Proxy pool settings."""
    enabled: bool = True
    force_proxy_platforms: list[str] = Field(default_factory=lambda: ["youtube.com", "youtu.be"])
    no_proxy_platforms: list[str] = Field(default_factory=list)
    health_check_interval_seconds: int = 300
    health_check_url: str = "https://www.google.com"
    rotation_strategy: Literal["round_robin", "random", "least_used", "least_errors"] = "round_robin"

    @field_validator("force_proxy_platforms", "no_proxy_platforms", mode="before")
    @classmethod
    def parse_platforms(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v


class CookieSettings(BaseModel):
    """yt-dlp cookie settings."""
    enabled: bool = True
    cookies_dir: pathlib.Path = pathlib.Path("data/cookies")
    validate_on_startup: bool = False
    cookie_platforms: list[str] = Field(
        default_factory=lambda: ["youtube", "instagram", "twitter", "tiktok", "reddit", "facebook"]
    )

    @field_validator("cookie_platforms", mode="before")
    @classmethod
    def parse_platforms(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v


class RedditSettings(BaseModel):
    """Reddit API settings."""
    user_agent: str = "MEDDOWBOT/1.0.0"
    enabled: bool = False
    max_posts_per_request: int = 50


class ObservabilitySettings(BaseModel):
    """Logging and metrics settings."""
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "console"
    metrics_port: int = 9090


class Settings(BaseSettings):
    """
    Global application settings.
    Using a unique prefix to avoid ANY system environment collisions.
    """
    model_config = SettingsConfigDict(
        env_prefix="BOT_CONF_",  # Using a unique prefix
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    env: Literal["dev", "prod", "test"] = "dev"
    version: str = "1.0.0"

    bot: BotSettings
    local_api: LocalApiSettings = Field(default_factory=LocalApiSettings)
    database: DatabaseSettings
    redis: RedisSettings = Field(default_factory=RedisSettings)
    worker: WorkerSettings = Field(default_factory=WorkerSettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    disk: DiskSettings = Field(default_factory=DiskSettings)
    ffmpeg: FFmpegSettings = Field(default_factory=FFmpegSettings)
    
    # RENAMED to break any system variable connections
    downloader_proxies: ProxySettings = Field(default_factory=ProxySettings)
    
    cookies: CookieSettings = Field(default_factory=CookieSettings)
    reddit: RedditSettings = Field(default_factory=RedditSettings)
    obs: ObservabilitySettings = Field(default_factory=ObservabilitySettings)

    @property
    def proxy(self) -> ProxySettings:
        """Alias for downloader_proxies to keep code working."""
        return self.downloader_proxies


settings: Settings

try:
    import os
    # Final cleanup: scrub any colliding vars from the process environment
    # so Pydantic NEVER sees them.
    for k in list(os.environ.keys()):
        if k in ["PROXY", "PROXY_POOL", "MB_PROXY", "MB_PROXY_CONFIG"]:
            del os.environ[k]

    settings = Settings()  # type: ignore
except Exception as e:
    # If it STILL fails, it's something truly bizarre. 
    # Attempt an emergency fallback load from only the .env file.
    if os.environ.get("MOCK_SETTINGS") == "1":
        settings = Settings(
            bot=BotSettings(token="dummy"),
            database=DatabaseSettings(url="sqlite+aiosqlite:///:memory:"),
        )
    else:
        # Emergency: Instantiate with defaults and load ONLY from init
        print(f"FAILED TO LOAD CONFIG: {e}")
        raise e
