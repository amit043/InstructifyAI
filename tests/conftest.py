import os
import uuid
from collections.abc import Generator
from io import BytesIO
from typing import List, Tuple

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("MINIO_ENDPOINT", "localhost")
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "test")
os.environ.setdefault("S3_BUCKET", "test")

from api.main import app, get_db, get_object_store
from models import Base, Project
from storage.object_store import ObjectStore

for var in [
    "DATABASE_URL",
    "MINIO_ENDPOINT",
    "MINIO_ACCESS_KEY",
    "MINIO_SECRET_KEY",
    "S3_BUCKET",
]:
    os.environ.pop(var, None)

PROJECT_ID_1 = uuid.uuid4()
PROJECT_ID_2 = uuid.uuid4()


class FakeS3Client:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def put_object(self, Bucket: str, Key: str, Body: bytes) -> None:  # noqa: N803
        self.store[Key] = Body

    def get_object(self, Bucket: str, Key: str) -> dict:  # noqa: N803
        return {"Body": BytesIO(self.store[Key])}

    def list_objects_v2(self, Bucket: str, Prefix: str) -> dict:  # noqa: N803
        keys = [k for k in self.store if k.startswith(Prefix)]
        return {"Contents": [{"Key": k} for k in keys]}

    def generate_presigned_url(
        self, operation: str, Params: dict, ExpiresIn: int
    ) -> str:  # noqa: N803
        return f"https://example.com/{Params['Key']}?X-Amz-Expires={ExpiresIn}"


@pytest.fixture
def test_app() -> (
    Generator[tuple[TestClient, ObjectStore, List[str], sessionmaker], None, None]
):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    with TestingSessionLocal() as session:
        session.add(
            Project(id=PROJECT_ID_1, name="P1", slug="p1", allow_versioning=False)
        )
        session.add(
            Project(id=PROJECT_ID_2, name="P2", slug="p2", allow_versioning=False)
        )
        session.commit()

    store = ObjectStore(client=FakeS3Client(), bucket="test")

    def override_get_db() -> Generator[Session, None, None]:
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_object_store] = lambda: store

    calls: List[str] = []

    from worker import main as worker_main

    def fake_delay(doc_id: str, request_id: str | None = None) -> None:
        calls.append(doc_id)

    worker_main.parse_document.delay = fake_delay

    client = TestClient(app)

    try:
        yield client, store, calls, TestingSessionLocal
    finally:
        app.dependency_overrides.clear()
