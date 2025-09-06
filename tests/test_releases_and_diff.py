import uuid

from sqlalchemy import select

from chunking.chunker import Block, chunk_blocks
from models import Document, DocumentStatus, DocumentVersion
from storage.object_store import export_key
from tests.conftest import PROJECT_ID_1
from worker.derived_writer import upsert_chunks


def _create_doc(SessionLocal, store, doc_id: str, text: str) -> None:
    blocks = [Block(text=text, page=1)]
    chunks = chunk_blocks(blocks, min_tokens=1, max_tokens=100)
    with SessionLocal() as db:
        doc = Document(id=doc_id, project_id=PROJECT_ID_1, source_type="text")
        db.add(doc)
        dv = DocumentVersion(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            project_id=PROJECT_ID_1,
            version=1,
            doc_hash=f"h-{text}",
            mime="text/plain",
            size=0,
            status=DocumentStatus.PARSED.value,
            meta={},
        )
        doc.latest_version_id = dv.id
        db.add(dv)
        db.commit()
        upsert_chunks(db, store, doc_id=doc_id, version=1, chunks=chunks)


def _update_doc(SessionLocal, store, doc_id: str, text: str) -> None:
    blocks = [Block(text=text, page=1)]
    chunks = chunk_blocks(blocks, min_tokens=1, max_tokens=100)
    with SessionLocal() as db:
        dv = db.scalar(
            select(DocumentVersion).where(DocumentVersion.document_id == doc_id)
        )
        assert dv is not None
        dv.doc_hash = f"h-{text}"
        db.commit()
        upsert_chunks(db, store, doc_id=doc_id, version=1, chunks=chunks)


def test_releases_and_diff(test_app) -> None:
    client, store, _, SessionLocal = test_app

    _create_doc(SessionLocal, store, "d1", "alpha")

    resp1 = client.post(
        f"/projects/{PROJECT_ID_1}/releases", headers={"X-Role": "curator"}
    )
    assert resp1.status_code == 200
    rel1 = resp1.json()["id"]

    _create_doc(SessionLocal, store, "d2", "beta")
    _update_doc(SessionLocal, store, "d1", "alpha2")

    resp2 = client.post(
        f"/projects/{PROJECT_ID_1}/releases", headers={"X-Role": "curator"}
    )
    assert resp2.status_code == 200
    rel2 = resp2.json()["id"]

    list_resp = client.get(
        f"/projects/{PROJECT_ID_1}/releases", headers={"X-Role": "viewer"}
    )
    assert list_resp.status_code == 200
    assert len(list_resp.json()["releases"]) == 2

    get_resp = client.get(f"/releases/{rel1}", headers={"X-Role": "viewer"})
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == rel1
    assert get_resp.json()["content_hash"]

    diff_resp = client.get(
        "/releases/diff",
        params={"base": rel1, "compare": rel2},
        headers={"X-Role": "viewer"},
    )
    diff = diff_resp.json()
    assert diff["added"] == ["d2"]
    assert diff["removed"] == []
    assert "d1" in diff["changed"]

    exp_resp = client.get(f"/releases/{rel2}/export", headers={"X-Role": "curator"})
    assert exp_resp.status_code == 200
    data = exp_resp.json()
    key = export_key(rel2, "data.jsonl")
    assert "X-Amz-Expires" in data["url"]
    assert not data["url"].startswith(key)
