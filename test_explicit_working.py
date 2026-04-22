from pydantic import BaseModel, Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class ProxySettings(BaseModel):
    enabled: bool = Field(True)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MB_", env_nested_delimiter="__")
    
    # We use a field that won't collide with MB_PROXY
    # but we still want to call it 'proxy' in code.
    proxy: ProxySettings = Field(default_factory=ProxySettings, validation_alias="MB_PROXY_POOL")

os.environ["MB_PROXY"] = "collision"
os.environ["MB_PROXY_POOL__ENABLED"] = "false"

try:
    settings = Settings()
    print(f"proxy.enabled: {settings.proxy.enabled}")
    print("Success")
except Exception as e:
    print(f"Error: {e}")
