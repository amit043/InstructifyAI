import uuid

from sqlalchemy import select

from models import Audit, Chunk, Document, DocumentStatus, DocumentVersion, Taxonomy
from tests.conftest import PROJECT_ID_1


def setup_document(SessionLocal) -> dict[str, str]:
    with SessionLocal() as db:
        doc_id = str(uuid.uuid4())
        dv_id = str(uuid.uuid4())
        c1_id = str(uuid.uuid4())
        c2_id = str(uuid.uuid4())
        doc = Document(
            id=doc_id,
            project_id=PROJECT_ID_1,
            source_type="pdf",
            latest_version_id=dv_id,
        )
        dv = DocumentVersion(
            id=dv_id,
            document_id=doc_id,
            project_id=PROJECT_ID_1,
            version=1,
            doc_hash="h",
            mime="text/plain",
            size=1,
            status=DocumentStatus.PARSED.value,
            meta={},
        )
        chunk1 = Chunk(
            id=c1_id,
            document_id=doc_id,
            version=1,
            order=1,
            content={},
            text_hash="t1",
            meta={
                "suggestions": {
                    "severity": {
                        "value": "ERROR",
                        "confidence": 0.9,
                        "rationale": "regex",
                        "span": "ERROR",
                    }
                }
            },
        )
        chunk2 = Chunk(
            id=c2_id,
            document_id=doc_id,
            version=1,
            order=2,
            content={},
            text_hash="t2",
            meta={
                "suggestions": {
                    "severity": {
                        "value": "INFO",
                        "confidence": 0.9,
                        "rationale": "regex",
                        "span": "INFO",
                    }
                }
            },
        )
        tax = Taxonomy(
            project_id=PROJECT_ID_1,
            version=1,
            fields=[{"name": "severity", "type": "enum", "required": True}],
        )
        db.add_all([doc, dv, chunk1, chunk2, tax])
        db.commit()
        return {"doc": doc_id, "dv": dv_id, "c1": c1_id, "c2": c2_id}


def test_accept_suggestion_and_metrics(test_app) -> None:
    client, _, _, SessionLocal = test_app
    ids = setup_document(SessionLocal)
    resp = client.post(
        f"/chunks/{ids['c1']}/suggestions/severity/accept",
        json={"user": "u"},
        headers={"X-Role": "curator"},
    )
    assert resp.status_code == 200
    with SessionLocal() as db:
        chunk = db.get(Chunk, ids["c1"])
        assert chunk.meta["severity"] == "ERROR"
        assert "suggestions" not in chunk.meta
        dv = db.get(DocumentVersion, ids["dv"])
        assert dv.status == DocumentStatus.NEEDS_REVIEW.value
        assert dv.meta["metrics"]["curation_completeness"] == 0.5
        audits = db.scalars(
            select(Audit).where(Audit.action == "accept_suggestion")
        ).all()
        assert len(audits) == 1

    resp2 = client.post(
        "/chunks/accept-suggestions",
        json={"chunk_ids": [ids["c2"]], "field": "severity", "user": "u"},
        headers={"X-Role": "curator"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["accepted"] == 1
    with SessionLocal() as db:
        chunk = db.get(Chunk, ids["c2"])
        assert chunk.meta["severity"] == "INFO"
        assert "suggestions" not in chunk.meta
        dv = db.get(DocumentVersion, ids["dv"])
        assert dv.status == DocumentStatus.PARSED.value
        assert dv.meta["metrics"]["curation_completeness"] == 1.0
        audits = db.scalars(
            select(Audit).where(Audit.action == "accept_suggestion")
        ).all()
        assert len(audits) == 2
    metrics = client.get(f"/documents/{ids['doc']}/metrics")
    assert metrics.json()["curation_completeness"] == 1.0


def test_accept_suggestion_not_found_returns_404(test_app) -> None:
    client, _, _, SessionLocal = test_app
    ids = setup_document(SessionLocal)
    resp = client.post(
        f"/chunks/{ids['c1']}/suggestions/missing/accept",
        json={"user": "u"},
        headers={"X-Role": "curator"},
    )
    assert resp.status_code == 404


def test_accept_suggestion_forbidden_for_viewer(test_app) -> None:
    client, _, _, SessionLocal = test_app
    ids = setup_document(SessionLocal)
    resp = client.post(
        f"/chunks/{ids['c1']}/suggestions/severity/accept",
        json={"user": "u"},
        headers={"X-Role": "viewer"},
    )
    assert resp.status_code == 403
