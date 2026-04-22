from pydantic import BaseModel, Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class ProxySettings(BaseModel):
    enabled: bool = Field(True, validation_alias=AliasChoices("MB_PROXY__ENABLED", "MB_PROXY_POOL__ENABLED"))

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MB_", env_nested_delimiter="__")
    
    proxy: ProxySettings = Field(
        default_factory=ProxySettings,
        # Give it an alias that won't collide with MB_PROXY
        validation_alias="MB_PROXY_POOL_JSON"
    )

os.environ["MB_PROXY"] = "collision"
os.environ["MB_PROXY__ENABLED"] = "false"

try:
    settings = Settings()
    print(f"proxy.enabled: {settings.proxy.enabled}")
    print("Success")
except Exception as e:
    import traceback
    traceback.print_exc()
