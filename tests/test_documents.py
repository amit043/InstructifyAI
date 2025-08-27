import json
import uuid

from sqlalchemy import select

from models import DocumentStatus, DocumentVersion
from tests.conftest import PROJECT_ID_1, PROJECT_ID_2
from worker.derived_writer import upsert_chunks


def test_listing_filters_and_pagination(test_app) -> None:
    client, _, _, SessionLocal = test_app
    resp1 = client.post(
        "/ingest",
        data={"project_id": str(PROJECT_ID_1)},
        files={"file": ("a.pdf", b"alpha", "application/pdf")},
    )
    doc1 = resp1.json()["doc_id"]
    resp2 = client.post(
        "/ingest",
        data={"project_id": str(PROJECT_ID_1)},
        files={"file": ("b.html", b"beta", "text/html")},
    )
    doc2 = resp2.json()["doc_id"]
    client.post(
        "/ingest",
        data={"project_id": str(PROJECT_ID_2)},
        files={"file": ("c.pdf", b"gamma", "application/pdf")},
    )

    with SessionLocal() as db:
        dv1 = db.scalar(
            select(DocumentVersion).where(DocumentVersion.document_id == doc1)
        )
        assert dv1 is not None
        dv1.status = DocumentStatus.PARSED.value
        dv1.meta = {"title": "alpha"}
        dv2 = db.scalar(
            select(DocumentVersion).where(DocumentVersion.document_id == doc2)
        )
        assert dv2 is not None
        dv2.meta = {"title": "beta"}
        db.commit()

    resp = client.get(
        "/documents",
        params={
            "project_id": str(PROJECT_ID_1),
            "status": "parsed",
            "type": "pdf",
            "q": "alpha",
        },
    )
    body = resp.json()
    assert len(body["documents"]) == 1
    assert body["documents"][0]["id"] == doc1

    resp_page1 = client.get(
        "/documents", params={"project_id": str(PROJECT_ID_1), "limit": 1, "offset": 0}
    )
    resp_page2 = client.get(
        "/documents", params={"project_id": str(PROJECT_ID_1), "limit": 1, "offset": 1}
    )
    id1 = resp_page1.json()["documents"][0]["id"]
    id2 = resp_page2.json()["documents"][0]["id"]
    assert id1 != id2


def test_get_document_manifest_and_chunks_stream(test_app) -> None:
    client, store, _, SessionLocal = test_app
    resp = client.post(
        "/ingest",
        data={"project_id": str(PROJECT_ID_1)},
        files={"file": ("doc.txt", b"hello world", "text/plain")},
    )
    doc_id = resp.json()["doc_id"]

    rows = []
    for i, text in enumerate(["alpha", "beta", "gamma"]):
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "document_id": doc_id,
                "version": 1,
                "order": i,
                "text": text,
                "text_hash": f"h{i}",
                "meta": '{"file_path": "doc.txt"}',
            }
        )

    with SessionLocal() as db:
        dv = db.scalar(
            select(DocumentVersion).where(DocumentVersion.document_id == doc_id)
        )
        assert dv is not None
        dv.status = DocumentStatus.PARSED.value
        db.commit()
        upsert_chunks(db, store, doc_id=doc_id, version=1, rows=rows)

    resp_doc = client.get(f"/documents/{doc_id}")
    assert resp_doc.status_code == 200
    assert resp_doc.json()["id"] == doc_id

    resp_manifest = client.get(f"/documents/{doc_id}/manifest")
    assert resp_manifest.status_code == 200
    assert resp_manifest.json()["files"] == ["doc.txt"]

    resp_chunks = client.get(f"/documents/{doc_id}/chunks?offset=1&limit=1")
    assert resp_chunks.status_code == 200
    lines = resp_chunks.text.strip().splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["content"]["text"] == "beta"
