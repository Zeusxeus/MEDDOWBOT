from pydantic import BaseModel, Field, AliasPath
from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class ProxySettings(BaseModel):
    enabled: bool = True

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MB_", env_nested_delimiter="__")
    
    proxy: ProxySettings = Field(
        default_factory=ProxySettings,
        validation_alias=AliasPath("proxy")
    )

os.environ["MB_PROXY"] = "collision"
os.environ["MB_PROXY__ENABLED"] = "false"

try:
    settings = Settings()
    print(f"proxy.enabled: {settings.proxy.enabled}")
except Exception as e:
    print(f"Error: {e}")
