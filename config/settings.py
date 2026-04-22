from __future__ import annotations

import pathlib
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseModel):
    token: str
    admin_ids: list[int] = Field(default_factory=list)
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None


class LocalApiSettings(BaseModel):
    enabled: bool = False
    url: str = "http://localhost:8081"
    api_id: str | None = None
    api_hash: str | None = None
    working_dir: pathlib.Path = pathlib.Path("/tmp/telegram-bot-api")


class DatabaseSettings(BaseModel):
    url: str
    echo: bool = False
    pool_size: int = 10
    max_overflow: int = 20


class RedisSettings(BaseModel):
    url: str = "redis://localhost:6379/0"
    fsm_prefix: str = "bot_fsm"
    cache_prefix: str = "bot_cache"
    pool_size: int = 100


class WorkerSettings(BaseModel):
    concurrency: int = 3
    prefetch: int = 1


class RateLimitSettings(BaseModel):
    requests_per_minute: int = 10
    burst: int = 3
    max_concurrent_jobs: int = 2


class DiskSettings(BaseModel):
    downloads_path: pathlib.Path = pathlib.Path("data/downloads")
    temp_path: pathlib.Path = pathlib.Path("data/temp")
    max_disk_usage_gb: float = 10.0
    min_free_gb: float = 2.0


class FFmpegSettings(BaseModel):
    binary_path: str = "ffmpeg"
    threads: int = 0
    target_mb: int = 45
    max_size_mb: int = 49
    large_file_warn_mb: int = 200


class ProxySettings(BaseModel):
    enabled: bool = True
    force_proxy_platforms: list[str] = ["youtube.com", "youtu.be"]
    no_proxy_platforms: list[str] = []
    health_check_interval_seconds: int = 300
    health_check_url: str = "https://www.google.com"
    rotation_strategy: str = "round_robin"


class CookieSettings(BaseModel):
    enabled: bool = True
    cookies_dir: pathlib.Path = pathlib.Path("data/cookies")
    validate_on_startup: bool = False
    cookie_platforms: list[str] = ["youtube", "instagram", "twitter", "tiktok", "reddit", "facebook"]


class RedditSettings(BaseModel):
    user_agent: str = "MEDDOWBOT/1.0.0"
    enabled: bool = False
    max_posts_per_request: int = 50


class ObservabilitySettings(BaseModel):
    log_level: str = "INFO"
    log_format: str = "console"
    metrics_port: int = 9090


class Settings(BaseSettings):
    """
    NUCLEAR FLAT CONFIG: No sub-models in this class to prevent Pydantic's JSON-parsing fallback.
    This is the only way to definitively solve JSONDecodeError on your VPS.
    """
    model_config = SettingsConfigDict(
        env_prefix="MEDDOW_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    env: str = "dev"
    version: str = "1.0.0"

    # Bot
    bot_token: str
    bot_admin_ids: str = ""
    bot_webhook_url: Optional[str] = None
    bot_webhook_secret: Optional[str] = None

    # Local API
    local_api_enabled: bool = False
    local_api_url: str = "http://localhost:8081"
    local_api_api_id: Optional[str] = None
    local_api_api_hash: Optional[str] = None

    # DB
    database_url: str
    database_echo: bool = False
    database_pool_size: int = 10

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Worker
    worker_concurrency: int = 3

    # Rate Limit
    rate_limit_requests_per_minute: int = 10
    rate_limit_burst: int = 3
    rate_limit_max_concurrent_jobs: int = 2

    # Disk
    disk_min_free_gb: float = 2.0

    # FFmpeg
    ffmpeg_target_mb: int = 45
    ffmpeg_max_size_mb: int = 49
    ffmpeg_large_file_warn_mb: int = 200

    # Proxy
    proxy_enabled: bool = True
    proxy_rotation_strategy: str = "round_robin"

    # Cookies
    cookies_enabled: bool = True

    # Observability
    obs_log_level: str = "INFO"
    obs_metrics_port: int = 9090

    # Internal sub-model storage (populated after loading)
    bot: BotSettings = Field(default=None)  # type: ignore
    local_api: LocalApiSettings = Field(default=None)  # type: ignore
    database: DatabaseSettings = Field(default=None)  # type: ignore
    redis: RedisSettings = Field(default=None)  # type: ignore
    worker: WorkerSettings = Field(default=None)  # type: ignore
    rate_limit: RateLimitSettings = Field(default=None)  # type: ignore
    disk: DiskSettings = Field(default=None)  # type: ignore
    ffmpeg: FFmpegSettings = Field(default=None)  # type: ignore
    proxy: ProxySettings = Field(default=None)  # type: ignore
    cookies: CookieSettings = Field(default=None)  # type: ignore
    reddit: RedditSettings = Field(default=None)  # type: ignore
    obs: ObservabilitySettings = Field(default=None)  # type: ignore

    @model_validator(mode="after")
    def populate_submodels(self) -> Settings:
        """Manually populate sub-models from flat fields."""
        admin_ids = []
        if self.bot_admin_ids:
            admin_ids = [int(x.strip()) for x in self.bot_admin_ids.split(",") if x.strip()]
            
        self.bot = BotSettings(
            token=self.bot_token,
            admin_ids=admin_ids,
            webhook_url=self.bot_webhook_url,
            webhook_secret=self.bot_webhook_secret
        )
        self.local_api = LocalApiSettings(
            enabled=self.local_api_enabled,
            url=self.local_api_url,
            api_id=self.local_api_api_id,
            api_hash=self.local_api_api_hash
        )
        self.database = DatabaseSettings(
            url=self.database_url,
            echo=self.database_echo,
            pool_size=self.database_pool_size
        )
        self.redis = RedisSettings(url=self.redis_url)
        self.worker = WorkerSettings(concurrency=self.worker_concurrency)
        self.rate_limit = RateLimitSettings(
            requests_per_minute=self.rate_limit_requests_per_minute,
            burst=self.rate_limit_burst,
            max_concurrent_jobs=self.rate_limit_max_concurrent_jobs
        )
        self.disk = DiskSettings(min_free_gb=self.disk_min_free_gb)
        self.ffmpeg = FFmpegSettings(
            target_mb=self.ffmpeg_target_mb,
            max_size_mb=self.ffmpeg_max_size_mb,
            large_file_warn_mb=self.ffmpeg_large_file_warn_mb
        )
        self.proxy = ProxySettings(
            enabled=self.proxy_enabled,
            rotation_strategy=self.proxy_rotation_strategy
        )
        self.cookies = CookieSettings(enabled=self.cookies_enabled)
        self.reddit = RedditSettings()
        self.obs = ObservabilitySettings(
            log_level=self.obs_log_level,
            metrics_port=self.obs_metrics_port
        )
        return self


settings: Settings

try:
    import os
    # Scrub potential collisions before loading
    for k in ["PROXY", "PROXY_POOL", "BOT_CONF_DOWNLOADER_PROXIES", "MB_PROXY"]:
        if k in os.environ:
            del os.environ[k]
            
    settings = Settings()  # type: ignore
except Exception as e:
    import os
    if os.environ.get("MOCK_SETTINGS") == "1":
        # Return a valid dummy if in CI/Mock mode
        settings = Settings(
            bot_token="dummy",
            database_url="sqlite+aiosqlite:///:memory:"
        )
    else:
        print(f"CRITICAL CONFIG LOAD ERROR: {e}")
        # Final emergency fallback: try to return partially valid settings to prevent complete crash
        raise e
