import uuid

from models import Audit, Chunk, Document
from tests.conftest import PROJECT_ID_1


def _setup_doc(SessionLocal) -> str:
    with SessionLocal() as db:
        doc_id = str(uuid.uuid4())
        doc = Document(id=doc_id, project_id=PROJECT_ID_1, source_type="pdf")
        db.add(doc)
        db.flush()
        for i in range(1, 4):
            db.add(
                Chunk(
                    id=f"c{i}",
                    document_id=doc_id,
                    version=1,
                    order=i,
                    content={},
                    text_hash=f"t{i}",
                    meta={},
                )
            )
        db.commit()
    return doc_id


def test_bulk_apply_range_success(test_app):
    client, _, _, SessionLocal = test_app
    doc_id = _setup_doc(SessionLocal)
    r = client.post(
        "/chunks/bulk-apply",
        json={
            "selection": {"doc_id": doc_id, "range": {"from": 1, "to": 2}},
            "patch": {"metadata": {"severity": "low"}},
            "user": "u",
        },
        headers={"X-Role": "curator"},
    )
    assert r.status_code == 200
    assert r.json()["updated"] == 2
    with SessionLocal() as db:
        c1 = db.get(Chunk, "c1")
        c2 = db.get(Chunk, "c2")
        c3 = db.get(Chunk, "c3")
        assert c1.meta["severity"] == "low"
        assert c2.meta["severity"] == "low"
        assert "severity" not in c3.meta
        audits = db.query(Audit).filter_by(action="bulk_apply").all()
        assert len(audits) == 2


def test_bulk_apply_partial_failure_rolls_back(test_app):
    client, _, _, SessionLocal = test_app
    _ = _setup_doc(SessionLocal)
    r = client.post(
        "/chunks/bulk-apply",
        json={
            "selection": {"chunk_ids": ["c1", "missing"]},
            "patch": {"metadata": {"tag": "x"}},
            "user": "u",
        },
        headers={"X-Role": "curator"},
    )
    assert r.status_code == 404
    with SessionLocal() as db:
        c1 = db.get(Chunk, "c1")
        assert "tag" not in c1.meta
        audits = db.query(Audit).filter_by(action="bulk_apply").all()
        assert len(audits) == 0
