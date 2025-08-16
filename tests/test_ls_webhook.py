import uuid

from models import Audit, Chunk, Document
from tests.conftest import PROJECT_ID_1


def _setup_chunk(SessionLocal) -> str:
    with SessionLocal() as db:
        doc_id = str(uuid.uuid4())
        doc = Document(id=doc_id, project_id=PROJECT_ID_1, source_type="pdf")
        db.add(doc)
        db.flush()
        chunk = Chunk(
            id="c1",
            document_id=doc_id,
            version=1,
            order=1,
            content={},
            text_hash="t1",
            meta={},
        )
        db.add(chunk)
        db.commit()
    return "c1"


def test_webhook_forbidden_for_viewer(test_app):
    client, _, _, SessionLocal = test_app
    _setup_chunk(SessionLocal)
    r = client.post(
        "/webhooks/label-studio",
        json={"chunk_id": "c1", "user": "u", "metadata": {"severity": "high"}},
        headers={"X-Role": "viewer"},
    )
    assert r.status_code == 403


def test_webhook_idempotent(test_app):
    client, _, _, SessionLocal = test_app
    _setup_chunk(SessionLocal)
    payload = {"chunk_id": "c1", "user": "u", "metadata": {"severity": "high"}}
    r1 = client.post(
        "/webhooks/label-studio",
        json=payload,
        headers={"X-Role": "curator"},
    )
    assert r1.status_code == 200
    r2 = client.post(
        "/webhooks/label-studio",
        json=payload,
        headers={"X-Role": "curator"},
    )
    assert r2.status_code == 200
    with SessionLocal() as db:
        chunk = db.get(Chunk, "c1")
        assert chunk.meta["severity"] == "high"
        assert chunk.rev == 2
        audits = db.query(Audit).filter_by(chunk_id="c1").all()
        assert len(audits) == 1
