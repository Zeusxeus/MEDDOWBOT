from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class SubModel(BaseModel):
    enabled: bool = True

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MB_", env_nested_delimiter="__")
    sub: SubModel = Field(validation_alias="MB_SUB_SETTINGS")

os.environ["MB_SUB"] = "collision"
os.environ["MB_SUB_SETTINGS__ENABLED"] = "false"

try:
    settings = Settings()
    print(f"sub.enabled: {settings.sub.enabled}")
except Exception as e:
    print(f"Error: {e}")
