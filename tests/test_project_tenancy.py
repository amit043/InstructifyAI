import uuid

import pytest
from fastapi import HTTPException

from storage.object_store import derived_key, signed_url
from tests.conftest import PROJECT_ID_1, PROJECT_ID_2


def _ingest(client, project_id: uuid.UUID) -> str:
    resp = client.post(
        "/ingest",
        data={"project_id": str(project_id)},
        files={"file": ("f.txt", b"data", "text/plain")},
    )
    assert resp.status_code == 200
    return resp.json()["doc_id"]


def test_document_access_scoped(test_app) -> None:
    client, _, _, _ = test_app
    doc1 = _ingest(client, PROJECT_ID_1)
    doc2 = _ingest(client, PROJECT_ID_2)

    resp_ok = client.get(
        f"/documents/{doc1}", headers={"X-Project-ID": str(PROJECT_ID_1)}
    )
    assert resp_ok.status_code == 200

    resp_forbidden = client.get(
        f"/documents/{doc2}", headers={"X-Project-ID": str(PROJECT_ID_1)}
    )
    assert resp_forbidden.status_code == 403


def test_presigned_url_scoped(test_app) -> None:
    client, store, _, SessionLocal = test_app
    doc1 = _ingest(client, PROJECT_ID_1)
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            signed_url(
                store,
                derived_key(doc1, "chunks.jsonl"),
                db=db,
                project_id=str(PROJECT_ID_2),
            )
        assert exc.value.status_code == 403
