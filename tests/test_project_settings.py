import json

import sqlalchemy as sa

from models import Chunk as ChunkModel
from models import Project, Taxonomy
from storage.object_store import derived_key, export_key
from tests.conftest import PROJECT_ID_1
from worker import main as worker_main


def test_project_settings_update_and_rbac(test_app) -> None:
    client, _, _, _ = test_app
    pid = str(PROJECT_ID_1)

    # defaults
    resp = client.get(f"/projects/{pid}/settings")
    assert resp.status_code == 200
    assert resp.json()["use_rules_suggestor"] is True

    # viewer cannot patch
    forbidden = client.patch(
        f"/projects/{pid}/settings",
        json={"use_rules_suggestor": False},
        headers={"X-Role": "viewer"},
    )
    assert forbidden.status_code == 403

    # curator can patch
    updated = client.patch(
        f"/projects/{pid}/settings",
        json={"use_rules_suggestor": False, "max_suggestions_per_doc": 1},
        headers={"X-Role": "curator"},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["use_rules_suggestor"] is False
    assert body["max_suggestions_per_doc"] == 1

    # confirm persisted
    resp2 = client.get(f"/projects/{pid}/settings")
    assert resp2.json()["use_rules_suggestor"] is False


def _setup_worker(store, SessionLocal) -> None:
    worker_main.create_client = lambda **kwargs: store.client
    worker_main.settings.s3_bucket = store.bucket
    worker_main.SessionLocal = SessionLocal


def _add_taxonomy(SessionLocal) -> None:
    with SessionLocal() as session:
        session.add(Taxonomy(project_id=PROJECT_ID_1, version=1, fields=[]))
        session.commit()


def _put_chunk(store, doc_id: str) -> None:
    chunk = {
        "doc_id": doc_id,
        "chunk_id": f"{doc_id}-c1",
        "order": 0,
        "rev": 1,
        "content": {"type": "text", "text": "Step 1: start ERROR INC-42 on 2024-01-01"},
        "source": {"page": 1, "section_path": ["A"]},
        "text_hash": "h",
        "metadata": {
            "suggestions": {
                "severity": {"value": "ERROR"},
                "step_id": {"value": "Step 1"},
            }
        },
    }
    store.put_bytes(
        derived_key(doc_id, "chunks.jsonl"),
        (json.dumps(chunk) + "\n").encode("utf-8"),
    )


def test_worker_respects_settings_toggle(test_app) -> None:
    client, store, _, SessionLocal = test_app
    _setup_worker(store, SessionLocal)
    pid = str(PROJECT_ID_1)

    html = "<html><body>Step 1: start ERROR INC-42 on 2024-01-01</body></html>".encode(
        "utf-8"
    )

    resp1 = client.post(
        "/ingest",
        data={"project_id": pid},
        files={"file": ("a.html", html, "text/html")},
    )
    doc1 = resp1.json()["doc_id"]
    worker_main.parse_document(doc1)
    with SessionLocal() as db:
        chunk1 = db.scalar(sa.select(ChunkModel).where(ChunkModel.document_id == doc1))
        assert chunk1 is not None
        assert "suggestions" in chunk1.meta

    with SessionLocal() as db:
        proj = db.get(Project, PROJECT_ID_1)
        assert proj is not None
        proj.use_rules_suggestor = False
        db.commit()

    html2 = "<html><body>Step 2: start ERROR INC-99 on 2024-01-02</body></html>".encode(
        "utf-8"
    )
    resp2 = client.post(
        "/ingest",
        data={"project_id": pid},
        files={"file": ("b.html", html2, "text/html")},
    )
    doc2 = resp2.json()["doc_id"]
    worker_main.parse_document(doc2)
    with SessionLocal() as db:
        chunk2 = db.scalar(sa.select(ChunkModel).where(ChunkModel.document_id == doc2))
        assert chunk2 is not None
        assert "suggestions" not in chunk2.meta


def test_exporter_respects_settings_toggle(test_app) -> None:
    client, store, _, SessionLocal = test_app
    _add_taxonomy(SessionLocal)
    pid = str(PROJECT_ID_1)
    _put_chunk(store, "d1")

    template = "{{ chunk.metadata | tojson }}"
    resp1 = client.post(
        "/export/jsonl",
        json={"project_id": pid, "doc_ids": ["d1"], "template": template},
        headers={"X-Role": "curator"},
    )
    key1 = export_key(resp1.json()["export_id"], "data.jsonl")
    data1 = store.get_bytes(key1).decode("utf-8").strip()
    assert "suggestions" in data1

    client.patch(
        f"/projects/{pid}/settings",
        json={"use_rules_suggestor": False},
        headers={"X-Role": "curator"},
    )
    resp2 = client.post(
        "/export/jsonl",
        json={"project_id": pid, "doc_ids": ["d1"], "template": template},
        headers={"X-Role": "curator"},
    )
    key2 = export_key(resp2.json()["export_id"], "data.jsonl")
    data2 = store.get_bytes(key2).decode("utf-8").strip()
    assert "suggestions" not in data2
    assert resp1.json()["export_id"] != resp2.json()["export_id"]
