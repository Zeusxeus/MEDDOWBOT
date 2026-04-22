import json
from typing import Any, Tuple, Type
from pydantic import BaseModel, Field
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
    EnvSettingsSource,
    DotEnvSettingsSource,
    PydanticBaseSettingsSource
)
import os

class ProxySettings(BaseModel):
    enabled: bool = True

class RobustEnvSettingsSource(EnvSettingsSource):
    def decode_complex_value(self, field_name: str, field: FieldInfo, value: str) -> Any:
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}

class RobustDotEnvSettingsSource(DotEnvSettingsSource):
    def decode_complex_value(self, field_name: str, field: FieldInfo, value: str) -> Any:
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MB_", env_nested_delimiter="__")
    proxy: ProxySettings = Field(default_factory=ProxySettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            RobustEnvSettingsSource(settings_cls),
            RobustDotEnvSettingsSource(settings_cls),
            file_secret_settings,
        )

os.environ["MB_PROXY"] = "collision-not-json"
os.environ["MB_PROXY__ENABLED"] = "false"

try:
    settings = Settings()
    print(f"proxy.enabled: {settings.proxy.enabled}")
    print("Success")
except Exception as e:
    import traceback
    traceback.print_exc()
