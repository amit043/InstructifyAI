from __future__ import annotations

import sqlalchemy as sa

from models import Chunk as ChunkModel
from models import Project
from tests.conftest import PROJECT_ID_1
from worker import main as worker_main
from worker.suggestors import suggest


def _setup_worker(store, SessionLocal) -> None:
    worker_main.create_client = lambda **kwargs: store.client
    worker_main.settings.s3_bucket = store.bucket
    worker_main.SessionLocal = SessionLocal


def test_severity_detector() -> None:
    result = suggest("something ERROR happened")
    assert result["severity"]["value"] == "ERROR"


def test_step_id_detector() -> None:
    result = suggest("Step 2: run task")
    val = result["step_id"]["value"]
    assert isinstance(val, str) and val.startswith("Step 2")


def test_ticket_id_detector() -> None:
    result = suggest("Refer to BUG-1234 for details")
    assert result["ticket_id"]["value"] == "BUG-1234"


def test_datetime_detector() -> None:
    result = suggest("Logged on 2024-01-01T10:00:00")
    assert result["datetime"]["value"] == "2024-01-01T10:00:00"


def test_suggestor_toggle_and_limit() -> None:
    text = "Step 1: start process ERROR in INC-1234 on 2024-01-01"
    assert suggest(text, use_rules_suggestor=False) == {}
    limited = suggest(text, max_suggestions=1)
    assert len(limited) == 1


def test_pipeline_populates_suggestions(test_app) -> None:
    client, store, _, SessionLocal = test_app
    _setup_worker(store, SessionLocal)
    html = "<html><body>Step 1: start ERROR INC-42 on 2024-01-01</body></html>".encode(
        "utf-8"
    )
    resp = client.post(
        "/ingest",
        data={"project_id": str(PROJECT_ID_1)},
        files={"file": ("x.html", html, "text/html")},
    )
    doc_id = resp.json()["doc_id"]
    worker_main.parse_document(doc_id, 1)
    with SessionLocal() as db:
        chunk = db.scalar(sa.select(ChunkModel).where(ChunkModel.document_id == doc_id))
        assert chunk is not None
        sug = chunk.meta["suggestions"]
        assert sug["severity"]["value"] == "ERROR"
        step_val = sug["step_id"]["value"]
        assert isinstance(step_val, str) and step_val.startswith("Step 1")
        assert sug["ticket_id"]["value"] == "INC-42"
        assert sug["datetime"]["value"] == "2024-01-01"


def test_pipeline_respects_project_limit(test_app) -> None:
    client, store, _, SessionLocal = test_app
    _setup_worker(store, SessionLocal)
    with SessionLocal() as db:
        proj = db.get(Project, PROJECT_ID_1)
        assert proj is not None
        proj.max_suggestions_per_doc = 2
        db.commit()
    html = "<html><body>Step 1: start ERROR INC-42 on 2024-01-01</body></html>".encode(
        "utf-8"
    )
    resp = client.post(
        "/ingest",
        data={"project_id": str(PROJECT_ID_1)},
        files={"file": ("x.html", html, "text/html")},
    )
    doc_id = resp.json()["doc_id"]
    worker_main.parse_document(doc_id, 1)
    with SessionLocal() as db:
        chunk = db.scalar(sa.select(ChunkModel).where(ChunkModel.document_id == doc_id))
        assert chunk is not None
        sug = chunk.meta["suggestions"]
        assert set(sug.keys()) == {"severity", "step_id"}
