from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    env: Literal["DEV", "TEST", "PROD"] = "DEV"
    database_url: str
    redis_url: str = "redis://redis:6379/0"
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_secure: bool = False
    s3_bucket: str
    export_signed_url_expiry_seconds: int = 600

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache()
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
