import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from chunking.chunker import Chunk, ChunkContent, ChunkSource
from models import Base
from models import Chunk as ChunkModel
from storage.object_store import ObjectStore
from tests.conftest import FakeS3Client
from worker.derived_writer import upsert_chunks


@pytest.fixture()
def session_store():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)
    store = ObjectStore(client=FakeS3Client(), bucket="test")
    with TestingSession() as session:
        yield session, store


def _make_chunk(
    chunk_id: uuid.UUID, text: str, text_hash: str, order: int = 0
) -> Chunk:
    return Chunk(
        id=chunk_id,
        order=order,
        content=ChunkContent(type="text", text=text),
        source=ChunkSource(page=1, section_path=[]),
        text_hash=text_hash,
        metadata={},
    )


def test_idempotent_reparse(session_store):
    session, store = session_store
    doc_id = "doc1"
    version = 1
    cid = uuid.uuid4()
    chunk = _make_chunk(cid, "hello", "hash1")

    upsert_chunks(session, store, doc_id=doc_id, version=version, chunks=[chunk])
    first_rev = session.query(ChunkModel.rev).filter_by(id=str(cid)).scalar()
    assert first_rev == 1

    upsert_chunks(session, store, doc_id=doc_id, version=version, chunks=[chunk])
    second_rev = session.query(ChunkModel.rev).filter_by(id=str(cid)).scalar()
    assert second_rev == 1


def test_rev_bump_on_change(session_store):
    session, store = session_store
    doc_id = "doc2"
    version = 1
    cid = uuid.uuid4()
    chunk = _make_chunk(cid, "hello", "hash1")

    upsert_chunks(session, store, doc_id=doc_id, version=version, chunks=[chunk])
    rev1 = session.query(ChunkModel.rev).filter_by(id=str(cid)).scalar()
    assert rev1 == 1

    changed = _make_chunk(cid, "hello world", "hash2")
    upsert_chunks(session, store, doc_id=doc_id, version=version, chunks=[changed])
    rev2 = session.query(ChunkModel.rev).filter_by(id=str(cid)).scalar()
    assert rev2 == 2


def test_deletes_removed_chunks(session_store):
    session, store = session_store
    doc_id = "doc3"
    version = 1
    cid1 = uuid.uuid4()
    cid2 = uuid.uuid4()
    chunk1 = _make_chunk(cid1, "a", "h1", order=0)
    chunk2 = _make_chunk(cid2, "b", "h2", order=1)

    upsert_chunks(
        session, store, doc_id=doc_id, version=version, chunks=[chunk1, chunk2]
    )
    ids = {id_ for (id_,) in session.query(ChunkModel.id).all()}
    assert str(cid1) in ids and str(cid2) in ids

    upsert_chunks(session, store, doc_id=doc_id, version=version, chunks=[chunk1])
    ids_after = {id_ for (id_,) in session.query(ChunkModel.id).all()}
    assert str(cid1) in ids_after
    assert str(cid2) not in ids_after
