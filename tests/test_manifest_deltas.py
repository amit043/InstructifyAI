import json

import sqlalchemy as sa

from models import DocumentVersion
from storage.object_store import derived_key, raw_key
from tests.conftest import PROJECT_ID_1
from worker import main as worker_main


def _setup_worker(store, SessionLocal):
    worker_main.create_client = lambda **kwargs: store.client
    worker_main.settings.s3_bucket = store.bucket
    worker_main.SessionLocal = SessionLocal


def test_manifest_deltas(test_app):
    client, store, _, SessionLocal = test_app
    _setup_worker(store, SessionLocal)

    # ingest initial document
    html1 = b"<html><body><h1>A</h1><p>alpha</p><h1>B</h1><p>beta</p></body></html>"
    resp = client.post(
        "/ingest",
        data={"project_id": str(PROJECT_ID_1)},
        files={"file": ("a.html", html1, "text/html")},
    )
    doc_id = resp.json()["doc_id"]

    worker_main.parse_document(doc_id, 1)

    # mutate second paragraph
    html2 = b"<html><body><h1>A</h1><p>alpha</p><h1>B</h1><p>beta2</p></body></html>"
    store.put_bytes(raw_key(doc_id, "a.html"), html2)

    worker_main.parse_document(doc_id, 1)

    manifest = json.loads(store.client.store[derived_key(doc_id, "manifest.json")])
    assert manifest["deltas"] == {"added": 0, "removed": 0, "changed": 1}

    with SessionLocal() as db:
        dv = db.scalar(
            sa.select(DocumentVersion).where(DocumentVersion.document_id == doc_id)
        )
        assert dv is not None
        assert dv.meta["parse"]["counts"]["chunks"] == 2
        assert dv.meta["parse"]["deltas"] == {"added": 0, "removed": 0, "changed": 1}
