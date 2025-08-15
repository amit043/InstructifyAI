import pytest
from pydantic import ValidationError

from core.settings import Settings


def test_missing_database_url_raises() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_profile_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "TEST")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("MINIO_ENDPOINT", "localhost:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "test")
    monkeypatch.setenv("MINIO_SECRET_KEY", "test")
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    s = Settings()
    assert s.env == "TEST"
    assert s.database_url == "sqlite:///:memory:"
    monkeypatch.setenv("ENV", "DEV")
