from pydantic import BaseModel, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
import os
import json

class SubModel(BaseModel):
    enabled: bool = True

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MB_", env_nested_delimiter="__")
    sub: SubModel

# Simulate collision
os.environ["MB_SUB"] = "some-random-string-not-json"

try:
    settings = Settings()
    print("Success")
except Exception as e:
    print(type(e))
    print(e)
