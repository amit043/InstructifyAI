from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    env: Literal["DEV", "TEST", "PROD"] = "DEV"
    database_url: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    s3_bucket: str

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache()
def get_settings() -> Settings:
    return Settings()
