import json

import sqlalchemy as sa

from models import Chunk as ChunkModel
from models import (
    DocumentStatus,
    DocumentVersion,
    Project,
    Taxonomy,
)
from storage.object_store import export_key
from tests.conftest import PROJECT_ID_1
from worker import main as worker_main
from worker.main import parse_document


def _setup_worker(store, SessionLocal) -> None:
    worker_main.create_client = lambda **kwargs: store.client
    worker_main.settings.s3_bucket = store.bucket
    worker_main.SessionLocal = SessionLocal


def test_pii_detection_and_export_toggle(test_app) -> None:
    client, store, _, SessionLocal = test_app
    _setup_worker(store, SessionLocal)
    with SessionLocal() as db:
        proj = db.get(Project, PROJECT_ID_1)
        assert proj is not None
        proj.block_pii = True
        db.commit()
        db.add(Taxonomy(project_id=PROJECT_ID_1, version=1, fields=[]))
        db.commit()
    html = "<html><body>Reach me at test@example.com or 555-123-4567 ID123</body></html>".encode(
        "utf-8"
    )
    resp = client.post(
        "/ingest",
        data={"project_id": str(PROJECT_ID_1)},
        files={"file": ("x.html", html, "text/html")},
    )
    doc_id = resp.json()["doc_id"]
    parse_document(doc_id, 1)
    with SessionLocal() as db:
        chunk = db.scalar(sa.select(ChunkModel).where(ChunkModel.document_id == doc_id))
        assert chunk is not None
        reds = chunk.meta["suggestions"]["redactions"]
        texts = {r["text"] for r in reds}
        assert "test@example.com" in texts
        assert "555-123-4567" in texts
        ver = db.scalar(
            sa.select(DocumentVersion).where(DocumentVersion.document_id == doc_id)
        )
        assert ver is not None
        assert ver.meta["metrics"]["pii_count"] == 3
        assert ver.status == DocumentStatus.NEEDS_REVIEW.value
    payload = {
        "project_id": str(PROJECT_ID_1),
        "doc_ids": [doc_id],
        "template": "{{ chunk.content.text }}",
        "exclude_pii": True,
    }
    resp = client.post(
        "/export/jsonl",
        json=payload,
        headers={"X-Role": "curator"},
    )
    assert resp.status_code == 200
    data = resp.json()
    key = export_key(data["export_id"], "data.jsonl")
    content = store.get_bytes(key).decode("utf-8")
    assert "test@example.com" not in content
    assert "[REDACTED]" in content
    payload["exclude_pii"] = False
    resp2 = client.post(
        "/export/jsonl",
        json=payload,
        headers={"X-Role": "curator"},
    )
    data2 = resp2.json()
    key2 = export_key(data2["export_id"], "data.jsonl")
    content2 = store.get_bytes(key2).decode("utf-8")
    assert "test@example.com" in content2
