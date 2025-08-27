import pathlib

import sqlalchemy as sa

from models import DocumentVersion
from storage.object_store import derived_key
from tests.conftest import PROJECT_ID_1
from worker import main as worker_main

BASE = pathlib.Path(__file__).resolve().parent.parent


def _setup_worker(store, SessionLocal):
    worker_main.create_client = lambda **kwargs: store.client
    worker_main.settings.s3_bucket = store.bucket
    worker_main.SessionLocal = SessionLocal


def test_parse_pdf_and_write_chunks(test_app):
    client, store, _, SessionLocal = test_app
    _setup_worker(store, SessionLocal)

    data = (BASE / "examples/golden/sample.pdf").read_bytes()
    resp = client.post(
        "/ingest",
        data={"project_id": str(PROJECT_ID_1)},
        files={"file": ("sample.pdf", data, "application/pdf")},
    )
    doc_id = resp.json()["doc_id"]

    worker_main.parse_document(doc_id, 1)

    resp_chunks = client.get(f"/documents/{doc_id}/chunks")
    assert resp_chunks.json()["total"] > 0
    key = derived_key(doc_id, "chunks.jsonl")
    assert key in store.client.store


def test_parse_failure_sets_status(test_app):
    client, store, _, SessionLocal = test_app
    _setup_worker(store, SessionLocal)

    resp = client.post(
        "/ingest",
        data={"project_id": str(PROJECT_ID_1)},
        files={"file": ("x.bin", b"data", "application/octet-stream")},
    )
    doc_id = resp.json()["doc_id"]

    with SessionLocal() as db:
        dv = db.scalar(
            sa.select(DocumentVersion).where(DocumentVersion.document_id == doc_id)
        )
        assert dv is not None
        dv.mime = "application/x-unknown"
        db.commit()

    worker_main.parse_document(doc_id, 1)

    resp_doc = client.get(f"/documents/{doc_id}")
    body = resp_doc.json()
    assert body["status"] == "failed"
    assert "error" in body["metadata"]
