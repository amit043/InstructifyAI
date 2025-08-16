import worker.main as worker_main
from models import Chunk, DocumentStatus, DocumentVersion
from tests.conftest import PROJECT_ID_1


def test_quality_gates_parse_metrics(test_app) -> None:
    client, store, _, SessionLocal = test_app
    html = b"<html><body><table></table><p>text</p></body></html>"
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
        worker_main.parse_document(doc_id)
    finally:
        worker_main.SessionLocal = orig_session  # type: ignore[assignment]
        worker_main._get_store = orig_store  # type: ignore[assignment]
    with SessionLocal() as db:
        dv = db.query(DocumentVersion).filter_by(document_id=doc_id, version=1).one()
        metrics = dv.meta["metrics"]
        assert dv.status == DocumentStatus.NEEDS_REVIEW.value
        assert metrics["empty_chunk_ratio"] > 0.1
        assert metrics["html_section_path_coverage"] < 0.9


def test_quality_gates_after_metadata_change(test_app) -> None:
    client, store, _, SessionLocal = test_app
    payload = {
        "fields": [
            {
                "name": "severity",
                "type": "enum",
                "required": True,
                "options": ["low", "high"],
            }
        ]
    }
    client.put(
        f"/projects/{PROJECT_ID_1}/taxonomy",
        json=payload,
        headers={"X-Role": "curator"},
    )
    html = b"<html><body><h1>Title</h1><p>text</p></body></html>"
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
        worker_main.parse_document(doc_id)
    finally:
        worker_main.SessionLocal = orig_session  # type: ignore[assignment]
        worker_main._get_store = orig_store  # type: ignore[assignment]
    with SessionLocal() as db:
        dv = db.query(DocumentVersion).filter_by(document_id=doc_id, version=1).one()
        assert dv.status == DocumentStatus.NEEDS_REVIEW.value
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
    with SessionLocal() as db:
        dv = db.query(DocumentVersion).filter_by(document_id=doc_id, version=1).one()
        assert dv.status == DocumentStatus.PARSED.value
        assert dv.meta["metrics"]["curation_completeness"] == 1.0
