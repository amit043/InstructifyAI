import uuid

from models import Audit, Chunk, Document
from tests.conftest import PROJECT_ID_1


def _setup(SessionLocal) -> str:
    with SessionLocal() as db:
        doc_id = str(uuid.uuid4())
        doc = Document(id=doc_id, project_id=PROJECT_ID_1, source_type="pdf")
        db.add(doc)
        db.add(
            Chunk(
                id="c1",
                document_id=doc_id,
                version=1,
                order=1,
                content={},
                text_hash="t1",
                meta={"severity": "low"},
            )
        )
        db.commit()
    return doc_id


def test_taxonomy_enum_rename_migrates_chunks(test_app):
    client, _, _, SessionLocal = test_app
    client.put(
        f"/projects/{PROJECT_ID_1}/taxonomy",
        json={
            "fields": [{"name": "severity", "type": "enum", "options": ["low", "high"]}]
        },
        headers={"X-Role": "curator"},
    )
    _setup(SessionLocal)
    r = client.patch(
        f"/projects/{PROJECT_ID_1}/taxonomy",
        json={"field": "severity", "mapping": {"low": "minor"}, "user": "m"},
        headers={"X-Role": "curator"},
    )
    assert r.status_code == 200
    assert r.json()["migrated"] == 1
    tax = client.get(f"/projects/{PROJECT_ID_1}/taxonomy").json()
    opts = [f["options"] for f in tax["fields"] if f["name"] == "severity"][0]
    assert "minor" in opts and "low" not in opts
    with SessionLocal() as db:
        chunk = db.get(Chunk, "c1")
        assert chunk.meta["severity"] == "minor"
        assert chunk.meta["stale"] is True
        audit = (
            db.query(Audit).filter_by(chunk_id="c1", action="taxonomy_migration").one()
        )
        assert audit.before["severity"] == "low"
        assert audit.after["severity"] == "minor"
