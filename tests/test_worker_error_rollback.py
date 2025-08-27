import pytest
import sqlalchemy as sa

from models import DocumentStatus, DocumentVersion
from tests.conftest import PROJECT_ID_1
from worker import main as worker_main


def _setup_worker(store, SessionLocal):
    worker_main.create_client = lambda **kwargs: store.client
    worker_main.settings.s3_bucket = store.bucket
    worker_main.SessionLocal = SessionLocal


def test_parse_error_rolls_back(test_app, monkeypatch):
    client, store, _, SessionLocal = test_app
    _setup_worker(store, SessionLocal)

    resp = client.post(
        "/ingest",
        data={"project_id": str(PROJECT_ID_1)},
        files={"file": ("a.txt", b"data", "text/plain")},
    )
    doc_id = resp.json()["doc_id"]

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(worker_main, "_run_parse", boom)

    with pytest.raises(RuntimeError) as excinfo:
        worker_main.parse_document(doc_id, 1)
    assert "InFailedSqlTransaction" not in str(excinfo.value)

    with SessionLocal() as db:
        dv = db.scalar(
            sa.select(DocumentVersion).where(DocumentVersion.document_id == doc_id)
        )
        assert dv is not None
        assert dv.status == DocumentStatus.FAILED.value
        assert "error" in dv.meta
        assert dv.meta.get("error_artifact", "").startswith("http")
