from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class ProxySettings(BaseModel):
    enabled: bool = True

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MB_", env_nested_delimiter="__")
    proxy: ProxySettings = Field(default_factory=ProxySettings)

os.environ["MB_PROXY"] = "collision"
os.environ["MB_PROXY__ENABLED"] = "false"

# Scrub
for key in list(os.environ.keys()):
    if key == "MB_PROXY":
        del os.environ[key]

try:
    settings = Settings()
    print(f"proxy.enabled: {settings.proxy.enabled}")
    print("Success")
except Exception as e:
    print(f"Error: {e}")
