from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class ProxySettings(BaseModel):
    enabled: bool = True

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MB_", env_nested_delimiter="__", env_file=".env.test")
    proxy: ProxySettings = Field(default_factory=ProxySettings)

# Even if we scrub os.environ, DotEnvSettingsSource reads the file
if "MB_PROXY" in os.environ:
    del os.environ["MB_PROXY"]

try:
    settings = Settings()
    print(f"proxy.enabled: {settings.proxy.enabled}")
    print("Success")
except Exception as e:
    # print(f"Error: {e}")
    import traceback
    traceback.print_exc()
