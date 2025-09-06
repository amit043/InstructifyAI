from models import (
    Chunk,
    Document,
    DocumentStatus,
    DocumentVersion,
    Project,
)
from tests.conftest import PROJECT_ID_1


def test_jsonb_native_types_round_trip(test_app) -> None:
    _, _, _, SessionLocal = test_app

    # project list/dict defaults and updates
    with SessionLocal() as session:
        project = session.get(Project, PROJECT_ID_1)
        project.ocr_langs.append("fra")
        project.html_crawl_limits["max_pages"] = 10
        session.commit()

    with SessionLocal() as session:
        project = session.get(Project, PROJECT_ID_1)
        assert isinstance(project.ocr_langs, list)
        assert isinstance(project.html_crawl_limits, dict)
        assert project.ocr_langs[-1] == "fra"
        assert project.html_crawl_limits["max_pages"] == 10

        doc = Document(project_id=project.id, source_type="pdf")
        session.add(doc)
        session.flush()
        doc_id = doc.id

        version = DocumentVersion(
            document_id=doc_id,
            project_id=project.id,
            version=1,
            doc_hash="hash",
            mime="application/pdf",
            size=1,
            status=DocumentStatus.INGESTED.value,
            meta={"foo": "bar"},
        )
        session.add(version)
        session.flush()
        version_id = version.id

        chunk = Chunk(
            document_id=doc_id,
            version=1,
            order=1,
            content={"text": "hello"},
            text_hash="hash1",
            meta={"tags": ["a"]},
        )
        session.add(chunk)
        session.flush()
        chunk_id = chunk.id
        session.commit()

    with SessionLocal() as session:
        version = session.get(DocumentVersion, version_id)
        assert isinstance(version.meta, dict)
        assert version.meta["foo"] == "bar"
        version.meta["bar"] = "baz"
        session.commit()

    with SessionLocal() as session:
        version = session.get(DocumentVersion, version_id)
        assert version.meta["bar"] == "baz"

    with SessionLocal() as session:
        chunk = session.get(Chunk, chunk_id)
        assert isinstance(chunk.meta, dict)
        assert chunk.meta == {"tags": ["a"]}
        chunk.meta["tags"] = chunk.meta["tags"] + ["b"]
        session.commit()

    with SessionLocal() as session:
        chunk = session.get(Chunk, chunk_id)
        assert chunk.meta["tags"] == ["a", "b"]
