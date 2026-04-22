from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import os
from typing import Any, Union

class ProxySettings(BaseModel):
    enabled: bool = True

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MB_", env_nested_delimiter="__")
    
    proxy: Union[ProxySettings, str] = Field(default_factory=ProxySettings)

    @field_validator("proxy", mode="before")
    @classmethod
    def validate_proxy(cls, v: Any) -> Any:
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                # It's a string but not JSON. 
                # We return an empty dict so that nested fields can still be applied.
                return {}
        return v

os.environ["MB_PROXY"] = "http://some-proxy-url" # Collision
os.environ["MB_PROXY__ENABLED"] = "false"

try:
    settings = Settings()
    print(f"proxy: {settings.proxy}")
    print(f"type of proxy: {type(settings.proxy)}")
    print(f"proxy.enabled: {settings.proxy.enabled}")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
