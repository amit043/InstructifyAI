from sqlalchemy import select

from models import Audit, Chunk, Document, DocumentVersion
from tests.conftest import PROJECT_ID_1


def test_audit_csv_and_correlation(test_app):
    client, store, calls, SessionLocal = test_app
    with SessionLocal() as db:
        doc = Document(id="d1", project_id=PROJECT_ID_1, source_type="pdf")
        dv = DocumentVersion(
            id="dv1",
            document_id="d1",
            project_id=PROJECT_ID_1,
            version=1,
            doc_hash="h",
            mime="application/pdf",
            size=1,
            status="parsed",
            meta={},
        )
        doc.latest_version_id = dv.id
        chunk = Chunk(
            id="c1",
            document_id="d1",
            version=1,
            order=0,
            content={},
            text_hash="t",
            meta={"suggestions": {"field": {"value": "x"}}},
        )
        db.add_all([doc, dv, chunk])
        db.commit()
    resp = client.post(
        "/chunks/c1/suggestions/field/accept",
        json={"user": "tester"},
        headers={"X-Role": "curator", "X-Request-ID": "rid-1"},
    )
    assert resp.status_code == 200
    with SessionLocal() as db:
        audit = db.scalar(select(Audit).where(Audit.chunk_id == "c1"))
        assert audit is not None
        assert audit.request_id == "rid-1"
    json_resp = client.get("/audits")
    assert json_resp.status_code == 200
    assert json_resp.json()[0]["request_id"] == "rid-1"
    csv_resp = client.get("/audits", headers={"Accept": "text/csv"})
    assert "rid-1" in csv_resp.text
