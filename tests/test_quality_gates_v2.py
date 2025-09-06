import worker.main as worker_main
from core.metrics import enforce_quality_gates
from core.settings import get_settings
from models import DocumentStatus, DocumentVersion
from tests.conftest import PROJECT_ID_1


def test_quality_gates_v2_metrics(test_app) -> None:
    client, store, _, SessionLocal = test_app
    html = "<html><body><h1>Title</h1><p>漢字漢字</p></body></html>".encode("utf-8")
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
    settings = get_settings()
    with SessionLocal() as db:
        dv = db.query(DocumentVersion).filter_by(document_id=doc_id, version=1).one()
        metrics = dict(dv.meta["metrics"])
        metrics["ocr_ratio"] = 0.5
        dv.meta["metrics"] = metrics
        db.add(dv)
        db.commit()
        settings.text_coverage_threshold = 0.5
        settings.ocr_ratio_threshold = 0.1
        settings.utf_other_ratio_threshold = 0.2
        enforce_quality_gates(doc_id, dv.project_id, dv.version, db)
        db.commit()
        db.refresh(dv)
        assert dv.status == DocumentStatus.NEEDS_REVIEW.value
        settings.text_coverage_threshold = 0.0
        settings.ocr_ratio_threshold = 1.0
        settings.utf_other_ratio_threshold = 1.0
        enforce_quality_gates(doc_id, dv.project_id, dv.version, db)
        db.commit()
        db.refresh(dv)
        assert dv.status == DocumentStatus.PARSED.value
