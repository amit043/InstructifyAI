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


def _make_row(cid: uuid.UUID, order: int, text: str, text_hash: str):
    return {
        "id": str(cid),
        "document_id": "doc",
        "version": 1,
        "order": order,
        "text": text,
        "text_hash": text_hash,
        "meta": {},
    }


def test_upsert_dedup_in_batch(session_store):
    session, store = session_store
    cid = uuid.uuid4()
    rows = [
        _make_row(cid, 0, "a", "h0"),
        _make_row(cid, 1, "b", "h1"),
    ]
    upsert_chunks(session, store, doc_id="doc", version=1, rows=rows)
    records = session.query(ChunkModel).all()
    assert len(records) == 1
    assert records[0].order == 1
    assert records[0].content.get("text") == "b"
    assert records[0].text_hash == "h1"
