import uuid

from models import Chunk, Document, DocumentStatus, DocumentVersion, Taxonomy
from tests.conftest import PROJECT_ID_1


def setup(SessionLocal) -> dict[str, str]:
    with SessionLocal() as db:
        doc_id = str(uuid.uuid4())
        dv_id = str(uuid.uuid4())
        c1 = str(uuid.uuid4())
        c2 = str(uuid.uuid4())
        c3 = str(uuid.uuid4())
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
            id=c1,
            document_id=doc_id,
            version=1,
            order=1,
            content={},
            text_hash="t1",
            meta={"text_coverage": 0.2},
        )
        chunk2 = Chunk(
            id=c2,
            document_id=doc_id,
            version=1,
            order=2,
            content={},
            text_hash="t2",
            meta={
                "suggestions": {"severity": {"value": "ERROR"}},
                "severity": "INFO",
            },
        )
        chunk3 = Chunk(
            id=c3,
            document_id=doc_id,
            version=1,
            order=3,
            content={},
            text_hash="t3",
            meta={"ocr_conf_mean": 0.3},
        )
        tax = Taxonomy(
            project_id=PROJECT_ID_1,
            version=1,
            fields=[{"name": "severity", "type": "enum", "required": True}],
        )
        db.add_all([doc, dv, chunk1, chunk2, chunk3, tax])
        db.commit()
        return {"c1": c1, "c2": c2, "c3": c3}


def test_active_learning_queue(test_app) -> None:
    client, _, _, SessionLocal = test_app
    ids = setup(SessionLocal)
    resp = client.get(
        f"/curation/next?project_id={PROJECT_ID_1}&limit=5",
        headers={"X-Role": "curator"},
    )
    assert resp.status_code == 200
    assert resp.json() == [
        {
            "chunk_id": ids["c1"],
            "reasons": ["low_text_coverage", "missing_required_fields"],
        },
        {"chunk_id": ids["c2"], "reasons": ["suggestion_conflicts"]},
        {
            "chunk_id": ids["c3"],
            "reasons": ["low_ocr_conf", "missing_required_fields"],
        },
    ]
