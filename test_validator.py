from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import os
from typing import Any

class ProxySettings(BaseModel):
    enabled: bool = True
    url: str = "default"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MB_", env_nested_delimiter="__")
    
    proxy: ProxySettings = Field(default_factory=ProxySettings)

    @field_validator("proxy", mode="before")
    @classmethod
    def validate_proxy(cls, v: Any) -> Any:
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return {}
        return v

os.environ["MB_PROXY"] = "http://some-proxy-url"
os.environ["MB_PROXY__URL"] = "http://real-proxy-url"

try:
    settings = Settings()
    print(f"proxy.url: {settings.proxy.url}")
    print(f"proxy.enabled: {settings.proxy.enabled}")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
