from typing import Dict

from models import Chunk, Document, DocumentStatus, DocumentVersion
from tests.conftest import PROJECT_ID_1


def _add_doc(SessionLocal, doc_id: str, metadata: Dict) -> None:
    with SessionLocal() as session:
        doc = Document(id=doc_id, project_id=PROJECT_ID_1, source_type="text")
        session.add(doc)
        session.flush()
        version = DocumentVersion(
            document_id=doc_id,
            project_id=PROJECT_ID_1,
            version=1,
            doc_hash=f"h-{doc_id}",
            mime="text/plain",
            size=1,
            status=DocumentStatus.PARSED.value,
        )
        session.add(version)
        session.flush()
        doc.latest_version_id = version.id
        chunk = Chunk(
            id=f"{doc_id}-c1",
            document_id=doc_id,
            version=1,
            order=0,
            content={"type": "text", "text": "hello"},
            text_hash="t",
            meta=metadata,
        )
        session.add(chunk)
        session.commit()


def test_create_dataset(test_app) -> None:
    client, _, _, _ = test_app
    resp = client.post(
        "/datasets",
        json={"name": "ds1", "project_id": str(PROJECT_ID_1), "filters": {}},
        headers={"X-Role": "curator"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "ds1"
    assert data["project_id"] == str(PROJECT_ID_1)


def test_materialize_dataset_counts(test_app) -> None:
    client, store, _, SessionLocal = test_app
    _add_doc(SessionLocal, "d1", {})
    resp = client.post(
        "/datasets",
        json={
            "name": "ds2",
            "project_id": str(PROJECT_ID_1),
            "filters": {"doc_ids": ["d1"]},
        },
        headers={"X-Role": "curator"},
    )
    dataset_id = resp.json()["id"]
    resp = client.post(
        f"/datasets/{dataset_id}/materialize",
        headers={"X-Role": "curator"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["stats"]["rows"] > 0
    assert data["stats"]["docs"] == 1
    assert (
        store.client.store.get(f"derived/datasets/{dataset_id}/snapshot.jsonl")
        is not None
    )


def test_validate_dataset_fail_empty_label(test_app) -> None:
    client, _, _, SessionLocal = test_app
    _add_doc(SessionLocal, "d2", {"label": ""})
    resp = client.post(
        "/datasets",
        json={
            "name": "ds3",
            "project_id": str(PROJECT_ID_1),
            "filters": {"doc_ids": ["d2"]},
        },
        headers={"X-Role": "curator"},
    )
    dataset_id = resp.json()["id"]
    client.post(
        f"/datasets/{dataset_id}/materialize",
        headers={"X-Role": "curator"},
    )
    resp = client.post(
        "/exports/validate",
        json={"dataset_id": dataset_id},
        headers={"X-Role": "curator"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert any("empty label" in issue for issue in data["issues"])


def test_validate_dataset_pass(test_app) -> None:
    client, _, _, SessionLocal = test_app
    _add_doc(SessionLocal, "d3", {"label": "ok"})
    resp = client.post(
        "/datasets",
        json={
            "name": "ds4",
            "project_id": str(PROJECT_ID_1),
            "filters": {"doc_ids": ["d3"]},
        },
        headers={"X-Role": "curator"},
    )
    dataset_id = resp.json()["id"]
    client.post(
        f"/datasets/{dataset_id}/materialize",
        headers={"X-Role": "curator"},
    )
    resp = client.post(
        "/exports/validate",
        json={"dataset_id": dataset_id},
        headers={"X-Role": "curator"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "passed"
    assert data["issues"] == []
