import json
import uuid

import sqlalchemy as sa

from chunking.chunker import Block, chunk_blocks
from models import Document, DocumentVersion
from storage.object_store import derived_key
from tests.conftest import PROJECT_ID_1
from worker.derived_writer import upsert_chunks
from worker.pipeline.incremental import plan_deltas


def _create_doc(db, doc_id: str, parts: dict[str, str]) -> None:
    dv = DocumentVersion(
        document_id=doc_id,
        project_id=PROJECT_ID_1,
        version=1,
        doc_hash="h0",
        mime="application/pdf",
        size=0,
        status="parsed",
        meta={"parse": {"parts": parts}},
    )
    doc = Document(
        id=doc_id,
        project_id=PROJECT_ID_1,
        source_type="pdf",
        latest_version_id=dv.id,
    )
    db.add_all([doc, dv])
    db.commit()


def test_incremental_deltas_and_manifest(test_app) -> None:
    _, store, _, SessionLocal = test_app
    doc_id = str(uuid.uuid4())

    blocks1 = [
        Block(text="alpha", page=1, section_path=["intro"]),
        Block(text="beta", page=2, section_path=["body"]),
    ]
    parts1, deltas1 = plan_deltas(blocks1, {})
    chunks1 = chunk_blocks(blocks1)
    with SessionLocal() as db:
        _create_doc(db, doc_id, parts1)
        upsert_chunks(
            db,
            store,
            doc_id=doc_id,
            version=1,
            chunks=chunks1,
            metrics={},
            parts=parts1,
            deltas=deltas1,
        )

    blocks2 = [
        Block(text="alpha", page=1, section_path=["intro"]),
        Block(text="beta2", page=2, section_path=["body"]),
        Block(text="gamma", page=3, section_path=["tail"]),
    ]
    parts2, deltas2 = plan_deltas(blocks2, parts1)
    chunks2 = chunk_blocks(blocks2)
    assert chunks1[0].id == chunks2[0].id

    with SessionLocal() as db:
        db.execute(
            sa.update(DocumentVersion)
            .where(DocumentVersion.document_id == doc_id)
            .values(meta={"parse": {"parts": parts2}})
        )
        db.commit()
        upsert_chunks(
            db,
            store,
            doc_id=doc_id,
            version=1,
            chunks=chunks2,
            metrics={},
            parts=parts2,
            deltas=deltas2,
        )

    with SessionLocal() as db:
        refreshed = db.scalar(
            sa.select(DocumentVersion).where(DocumentVersion.document_id == doc_id)
        )
        assert refreshed is not None
        assert refreshed.meta["parse"]["parts"] == parts2

    manifest = json.loads(store.client.store[derived_key(doc_id, "manifest.json")])
    assert manifest["parts"] == parts2
    assert manifest["deltas"] == deltas2
