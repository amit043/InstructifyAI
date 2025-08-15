import pathlib

import pytest

pytest.importorskip("bs4")
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import parsers  # ensure registration
from chunking.chunker import chunk_blocks
from models import Base
from models import Chunk as ChunkModel
from parsers import registry
from storage.object_store import ObjectStore, derived_key
from tests.conftest import FakeS3Client
from worker.derived_writer import upsert_chunks

BASE = pathlib.Path(__file__).resolve().parent.parent


def _load(path: str) -> bytes:
    return (BASE / path).read_bytes()


def test_html_parser_and_chunker() -> None:
    data = _load("examples/golden/sample.html")
    blocks = list(registry.get("text/html").parse(data))
    assert any(b.type == "table_placeholder" for b in blocks)
    chunks = chunk_blocks(blocks, min_tokens=1, max_tokens=5)
    assert chunks == chunk_blocks(blocks, min_tokens=1, max_tokens=5)
    table_chunk = next(c for c in chunks if c.content.type == "table_placeholder")
    assert table_chunk.source.section_path == ["Title", "Section A"]
    assert chunks[0].source.section_path == ["Title"]


def test_pdf_parser() -> None:
    pytest.importorskip("fitz")
    data = _load("examples/golden/sample.pdf")
    blocks = list(registry.get("application/pdf").parse(data))
    assert blocks[0].section_path == ["INTRO"]
    chunks = chunk_blocks(blocks, min_tokens=1, max_tokens=5)
    assert chunks[0].source.page == 1


def test_derived_writer_idempotent() -> None:
    engine = create_engine("sqlite:///:memory:")
    SessionLocal = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    store = ObjectStore(client=FakeS3Client(), bucket="test")
    data = _load("examples/golden/sample.html")
    blocks = list(registry.get("text/html").parse(data))
    chunks = chunk_blocks(blocks, min_tokens=1, max_tokens=5)
    with SessionLocal() as db:
        upsert_chunks(db, store, doc_id="d1", version=1, chunks=chunks)
        assert db.query(ChunkModel).count() == len(chunks)
        first = db.query(ChunkModel).filter_by(order=0).one()
        first.meta = {"label": "x"}
        first.rev = 2
        db.commit()
        blocks2 = list(registry.get("text/html").parse(data))
        chunks2 = chunk_blocks(blocks2, min_tokens=1, max_tokens=5)
        upsert_chunks(db, store, doc_id="d1", version=1, chunks=chunks2)
        assert db.query(ChunkModel).count() == len(chunks2)
        first2 = db.query(ChunkModel).filter_by(order=0).one()
        assert first2.meta == {"label": "x"}
        assert first2.rev == 2
        key = derived_key("d1", "chunks.jsonl")
        lines = store.get_bytes(key).decode().strip().splitlines()
        assert len(lines) == len(chunks2)
