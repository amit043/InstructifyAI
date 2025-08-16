import uuid

from models import Audit, Chunk, Document
from tests.conftest import PROJECT_ID_1


def test_taxonomy_version_and_ls_config(test_app):
    client, _, _, _ = test_app
    payload = {
        "fields": [
            {
                "name": "severity",
                "type": "enum",
                "required": True,
                "helptext": "Severity level",
                "examples": ["low"],
                "options": ["low", "high"],
            }
        ]
    }
    r = client.put(
        f"/projects/{PROJECT_ID_1}/taxonomy",
        json=payload,
        headers={"X-Role": "curator"},
    )
    assert r.status_code == 200
    assert r.json()["version"] == 1
    r2 = client.put(
        f"/projects/{PROJECT_ID_1}/taxonomy",
        json=payload,
        headers={"X-Role": "curator"},
    )
    assert r2.json()["version"] == 2
    r3 = client.get(f"/projects/{PROJECT_ID_1}/taxonomy")
    assert r3.json()["version"] == 2
    assert r3.json()["fields"][0]["helptext"] == "Severity level"
    r4 = client.post("/label-studio/config", params={"project_id": PROJECT_ID_1})
    assert r4.status_code == 200
    assert "Severity level" in r4.text
    assert '<Choice value="low"/>' in r4.text
    r_forbidden = client.put(
        f"/projects/{PROJECT_ID_1}/taxonomy", json=payload, headers={"X-Role": "viewer"}
    )
    assert r_forbidden.status_code == 403


def test_webhook_and_bulk_apply(test_app):
    client, _, _, SessionLocal = test_app
    with SessionLocal() as db:
        doc_id = str(uuid.uuid4())
        doc = Document(id=doc_id, project_id=PROJECT_ID_1, source_type="pdf")
        db.add(doc)
        db.flush()
        c1 = Chunk(
            id="c1",
            document_id=doc_id,
            version=1,
            order=1,
            content={},
            text_hash="t1",
            meta={},
        )
        c2 = Chunk(
            id="c2",
            document_id=doc_id,
            version=1,
            order=2,
            content={},
            text_hash="t2",
            meta={},
        )
        db.add_all([c1, c2])
        db.commit()
    r_forbidden = client.post(
        "/webhooks/label-studio",
        json={"chunk_id": "c1", "user": "u", "metadata": {"severity": "high"}},
        headers={"X-Role": "viewer"},
    )
    assert r_forbidden.status_code == 403
    r = client.post(
        "/webhooks/label-studio",
        json={"chunk_id": "c1", "user": "u", "metadata": {"severity": "high"}},
        headers={"X-Role": "curator"},
    )
    assert r.status_code == 200
    with SessionLocal() as db:
        chunk = db.get(Chunk, "c1")
        assert chunk.meta["severity"] == "high"
        audits = db.query(Audit).filter_by(chunk_id="c1").all()
        assert len(audits) == 1
    rb = client.post(
        "/chunks/bulk-apply",
        json={
            "selection": {"chunk_ids": ["c1", "c2"]},
            "patch": {"metadata": {"tag": "x"}},
            "user": "u2",
        },
        headers={"X-Role": "curator"},
    )
    assert rb.status_code == 200
    with SessionLocal() as db:
        c1_db = db.get(Chunk, "c1")
        c2_db = db.get(Chunk, "c2")
        assert c1_db.meta["tag"] == "x"
        assert c2_db.meta["tag"] == "x"
        audits = db.query(Audit).filter_by(action="bulk_apply").all()
        assert len(audits) == 2
