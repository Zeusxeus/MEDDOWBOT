from __future__ import annotations

import pathlib
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator
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
    ULTRA-ROBUST FLAT CONFIG
    Environment variables are flat. Python objects are provided via @property.
    This prevents Pydantic from ever attempting JSON parsing on environment variables.
    """
    model_config = SettingsConfigDict(
        env_prefix="MEDDOW_",
        env_file=".env",
        extra="ignore",
    )

    env: str = "dev"
    version: str = "1.0.0"

    # Flat Environment Fields
    bot_token: str
    bot_admin_ids: str = ""
    bot_webhook_url: Optional[str] = None
    bot_webhook_secret: Optional[str] = None

    local_api_enabled: bool = False
    local_api_url: str = "http://127.0.0.1:8081"
    local_api_api_id: Optional[str] = None
    local_api_api_hash: Optional[str] = None

    database_url: str
    database_echo: bool = False
    database_pool_size: int = 10

    redis_url: str = "redis://127.0.0.1:6379/0"
    worker_concurrency: int = 3

    rate_limit_requests_per_minute: int = 10
    rate_limit_burst: int = 3
    rate_limit_max_concurrent_jobs: int = 2

    disk_min_free_gb: float = 2.0
    ffmpeg_target_mb: int = 45
    ffmpeg_max_size_mb: int = 49
    ffmpeg_large_file_warn_mb: int = 200

    proxy_enabled: bool = True
    proxy_rotation_strategy: str = "round_robin"
    cookies_enabled: bool = True
    obs_log_level: str = "INFO"
    obs_metrics_port: int = 9090

    # Dynamic Properties to satisfy existing bot code
    @property
    def bot(self) -> BotSettings:
        ids = [int(x.strip()) for x in self.bot_admin_ids.split(",") if x.strip()] if self.bot_admin_ids else []
        return BotSettings(token=self.bot_token, admin_ids=ids, webhook_url=self.bot_webhook_url, webhook_secret=self.bot_webhook_secret)

    @property
    def local_api(self) -> LocalApiSettings:
        return LocalApiSettings(enabled=self.local_api_enabled, url=self.local_api_url, api_id=self.local_api_api_id, api_hash=self.local_api_api_hash)

    @property
    def database(self) -> DatabaseSettings:
        return DatabaseSettings(url=self.database_url, echo=self.database_echo, pool_size=self.database_pool_size)

    @property
    def redis(self) -> RedisSettings:
        return RedisSettings(url=self.redis_url)

    @property
    def worker(self) -> WorkerSettings:
        return WorkerSettings(concurrency=self.worker_concurrency)

    @property
    def rate_limit(self) -> RateLimitSettings:
        return RateLimitSettings(requests_per_minute=self.rate_limit_requests_per_minute, burst=self.rate_limit_burst, max_concurrent_jobs=self.rate_limit_max_concurrent_jobs)

    @property
    def disk(self) -> DiskSettings:
        return DiskSettings(min_free_gb=self.disk_min_free_gb)

    @property
    def ffmpeg(self) -> FFmpegSettings:
        return FFmpegSettings(target_mb=self.ffmpeg_target_mb, max_size_mb=self.ffmpeg_max_size_mb, large_file_warn_mb=self.ffmpeg_large_file_warn_mb)

    @property
    def proxy(self) -> ProxySettings:
        return ProxySettings(enabled=self.proxy_enabled, rotation_strategy=self.proxy_rotation_strategy)

    @property
    def cookies(self) -> CookieSettings:
        return CookieSettings(enabled=self.cookies_enabled)

    @property
    def reddit(self) -> RedditSettings:
        return RedditSettings()

    @property
    def obs(self) -> ObservabilitySettings:
        return ObservabilitySettings(log_level=self.obs_log_level, metrics_port=self.obs_metrics_port)


settings: Settings

try:
    import os
    # Scrub system environment collisions before Pydantic sees them
    for k in ["PROXY", "PROXY_POOL", "MB_PROXY"]:
        if k in os.environ:
            del os.environ[k]
            
    settings = Settings()  # type: ignore
except Exception as e:
    if os.environ.get("MOCK_SETTINGS") == "1":
        settings = Settings(bot_token="dummy", database_url="sqlite+aiosqlite:///:memory:")
    else:
        print(f"FATAL: Settings initialization failed. Error: {e}")
        raise e
