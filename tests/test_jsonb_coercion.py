import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base
from models import Chunk as ChunkModel
from storage.object_store import ObjectStore
from tests.conftest import FakeS3Client
from worker.derived_writer import upsert_chunks


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_: JSONB, compiler, **kw):  # pragma: no cover - test helper
    return "JSON"


@pytest.fixture()
def session_store():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[ChunkModel.__table__])
    TestingSession = sessionmaker(bind=engine)
    store = ObjectStore(client=FakeS3Client(), bucket="test")
    with TestingSession() as session:
        yield session, store


def test_jsonb_coercion(session_store):
    session, store = session_store
    cid = uuid.uuid4()
    rows = [
        {
            "id": str(cid),
            "document_id": "doc",
            "version": 1,
            "order": 0,
            "text": "hello",
            "text_hash": "h1",
            "meta": '{"tags": ["a"]}',
        }
    ]
    upsert_chunks(session, store, doc_id="doc", version=1, rows=rows)
    chunk = session.get(ChunkModel, str(cid))
    assert isinstance(chunk.meta, dict)
    assert chunk.meta["tags"] == ["a"]
    assert isinstance(chunk.content, dict)
    assert chunk.content["text"] == "hello"
