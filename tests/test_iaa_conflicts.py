import worker.main as worker_main
from models import Audit, Chunk
from tests.conftest import PROJECT_ID_1


def test_iaa_and_conflicts(test_app) -> None:
    client, store, _, SessionLocal = test_app
    payload = {
        "fields": [
            {
                "name": "severity",
                "type": "enum",
                "required": False,
                "options": ["low", "high"],
            }
        ]
    }
    client.put(
        f"/projects/{PROJECT_ID_1}/taxonomy",
        json=payload,
        headers={"X-Role": "curator"},
    )
    html = b"<html><body><p>text</p></body></html>"
    resp = client.post(
        "/ingest",
        data={"project_id": str(PROJECT_ID_1)},
        files={"file": ("doc.html", html, "text/html")},
    )
    doc_id = resp.json()["doc_id"]
    orig_session = worker_main.SessionLocal
    orig_store = worker_main._get_store
    worker_main.SessionLocal = SessionLocal  # type: ignore[assignment]
    worker_main._get_store = lambda: store  # type: ignore[assignment]
    try:
        worker_main.parse_document(doc_id, 1)
    finally:
        worker_main.SessionLocal = orig_session  # type: ignore[assignment]
        worker_main._get_store = orig_store  # type: ignore[assignment]
    with SessionLocal() as db:
        chunk = db.query(Chunk).filter_by(document_id=doc_id, version=1).first()
        chunk_id = chunk.id
    client.post(
        "/chunks/bulk-apply",
        json={
            "selection": {"chunk_ids": [chunk_id]},
            "patch": {"metadata": {"severity": "low"}},
            "user": "u1",
        },
        headers={"X-Role": "curator"},
    )
    client.post(
        "/chunks/bulk-apply",
        json={
            "selection": {"chunk_ids": [chunk_id]},
            "patch": {"metadata": {"severity": "high"}},
            "user": "u2",
        },
        headers={"X-Role": "curator"},
    )
    resp = client.get(f"/documents/{doc_id}/metrics")
    data = resp.json()
    assert data["iaa"]["severity"] == 0.0
    with SessionLocal() as db:
        audits = db.query(Audit).filter_by(chunk_id=chunk_id).all()
        actions = [a.action for a in audits]
        assert any(a.endswith("_conflict") for a in actions)
