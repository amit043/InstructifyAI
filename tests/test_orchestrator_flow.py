import pathlib

import sqlalchemy as sa
from celery.canvas import chord  # type: ignore[import-untyped]

from models import Audit, DocumentStatus, DocumentVersion
from tests.conftest import PROJECT_ID_1
from worker import flow
from worker import main as worker_main
from worker.tasks import utils as task_utils

BASE = pathlib.Path(__file__).resolve().parent.parent


def _setup_worker(store, SessionLocal) -> None:
    worker_main.create_client = lambda **kwargs: store.client
    worker_main.settings.s3_bucket = store.bucket
    worker_main.SessionLocal = SessionLocal
    task_utils.SessionLocal = SessionLocal


def test_flow_updates_status_and_audits(test_app):
    client, store, _, SessionLocal = test_app
    _setup_worker(store, SessionLocal)

    data = (BASE / "examples/golden/sample.pdf").read_bytes()
    resp = client.post(
        "/ingest",
        data={"project_id": str(PROJECT_ID_1)},
        files={"file": ("sample.pdf", data, "application/pdf")},
    )
    doc_id = resp.json()["doc_id"]

    sig = flow.build_flow(doc_id, request_id="rid")
    sig.apply()

    with SessionLocal() as db:
        dv = db.scalar(
            sa.select(DocumentVersion).where(DocumentVersion.document_id == doc_id)
        )
        assert dv is not None
        assert dv.status == DocumentStatus.PARSED.value
        audits = db.query(Audit).filter_by(chunk_id=doc_id).all()
        assert [a.action for a in audits] == [
            "preflight",
            "normalize",
            "extract",
            "structure",
            "chunk_write",
            "finalize",
        ]
        assert all(a.request_id == "rid" for a in audits)


def test_build_flow_with_ocr_uses_chord():
    sig = flow.build_flow("doc1", do_ocr=True)
    tasks = sig.tasks
    assert isinstance(tasks[3], chord)
