from functools import lru_cache
from typing import Literal

from pydantic import Field
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
    suggestion_timeout_ms: int = 500
    max_suggestions_per_doc: int = 200
    ocr_langs: list[str] = Field(default_factory=list)
    min_text_len_for_ocr: int = 0
    html_crawl_max_depth: int = 2
    html_crawl_max_pages: int = 10
    curation_completeness_threshold: float = 0.8
    empty_chunk_ratio_threshold: float = 0.1
    html_section_path_coverage_threshold: float = 0.9
    text_coverage_threshold: float = 0.5
    ocr_ratio_threshold: float = 0.5
    utf_other_ratio_threshold: float = 0.2
    jwt_secret: str = "change-me"
    jwt_public_key: str | None = None
    rate_limit_window_seconds: int = 60
    rate_limit_max_per_minute: int = 60
    tables_as_text: bool = False
    ls_base_url: str | None = None
    ls_api_token: str | None = None
    enable_adapters_api: bool = False
    feature_doc_bindings: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache()
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
