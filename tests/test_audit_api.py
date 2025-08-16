from datetime import datetime, timedelta, timezone

from models import Audit, Chunk, Document, DocumentVersion
from tests.conftest import PROJECT_ID_1


def test_audit_filters_and_csv_stream(test_app):
    client, store, calls, SessionLocal = test_app
    with SessionLocal() as db:
        doc1 = Document(id="d1", project_id=PROJECT_ID_1, source_type="pdf")
        dv1 = DocumentVersion(
            id="dv1",
            document_id="d1",
            project_id=PROJECT_ID_1,
            version=1,
            doc_hash="h1",
            mime="application/pdf",
            size=1,
            status="parsed",
            meta={},
        )
        doc1.latest_version_id = dv1.id
        chunk1 = Chunk(
            id="c1",
            document_id="d1",
            version=1,
            order=0,
            content={},
            text_hash="t1",
            meta={},
        )
        doc2 = Document(id="d2", project_id=PROJECT_ID_1, source_type="pdf")
        dv2 = DocumentVersion(
            id="dv2",
            document_id="d2",
            project_id=PROJECT_ID_1,
            version=1,
            doc_hash="h2",
            mime="application/pdf",
            size=1,
            status="parsed",
            meta={},
        )
        doc2.latest_version_id = dv2.id
        chunk2 = Chunk(
            id="c2",
            document_id="d2",
            version=1,
            order=0,
            content={},
            text_hash="t2",
            meta={},
        )
        t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        audit1 = Audit(
            chunk_id="c1",
            user="u1",
            action="bulk_apply",
            before={},
            after={},
            created_at=t0,
        )
        audit2 = Audit(
            chunk_id="c1",
            user="u2",
            action="accept_suggestion",
            before={},
            after={},
            created_at=t0 + timedelta(days=1),
        )
        audit3 = Audit(
            chunk_id="c2",
            user="u1",
            action="bulk_apply",
            before={},
            after={},
            created_at=t0 + timedelta(days=2),
        )
        db.add_all(
            [
                doc1,
                dv1,
                chunk1,
                doc2,
                dv2,
                chunk2,
                audit1,
                audit2,
                audit3,
            ]
        )
        db.commit()

    resp = client.get("/audits", params={"doc_id": "d1"})
    assert {a["chunk_id"] for a in resp.json()} == {"c1"}

    resp = client.get("/audits", params={"user": "u1", "action": "bulk_apply"})
    assert {a["doc_id"] for a in resp.json()} == {"d1", "d2"}

    since = (t0 + timedelta(days=1)).isoformat()
    resp = client.get("/audits", params={"since": since})
    assert {a["chunk_id"] for a in resp.json()} == {"c1", "c2"}

    resp = client.get(
        "/audits",
        params={"doc_id": "d1", "user": "u2", "action": "accept_suggestion"},
    )
    data = resp.json()
    assert len(data) == 1 and data[0]["chunk_id"] == "c1"

    with client.stream(
        "GET", "/audits", headers={"Accept": "text/csv"}, params={"doc_id": "d1"}
    ) as csv_resp:
        lines = list(csv_resp.iter_lines())
    assert lines[0] == "chunk_id,doc_id,user,action,request_id,created_at"
    assert any("u2" in line for line in lines[1:])
