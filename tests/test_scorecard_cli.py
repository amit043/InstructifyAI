import uuid
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import Base, Chunk, Document, DocumentVersion, Project, Taxonomy
from scripts.scorecard import run


def _setup_db(path: Path, complete: bool) -> str:
    db_url = f"sqlite:///{path}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project_id = uuid.uuid4()
        db.add(Project(id=project_id, name="p", allow_versioning=False))
        tax = Taxonomy(
            id=uuid.uuid4(),
            project_id=project_id,
            version=1,
            fields=[{"name": "label", "required": True}],
        )
        doc = Document(id="d1", project_id=project_id, source_type="pdf")
        dv = DocumentVersion(
            id="dv1",
            document_id="d1",
            project_id=project_id,
            version=1,
            doc_hash="h",
            mime="application/pdf",
            size=1,
            status="parsed",
            meta={},
        )
        doc.latest_version_id = dv.id
        meta = {"label": "x"} if complete else {}
        chunk = Chunk(
            id="c1",
            document_id="d1",
            version=1,
            order=0,
            content={},
            text_hash="t",
            meta=meta,
        )
        db.add_all([tax, doc, dv, chunk])
        db.commit()
    return db_url


def test_scorecard_run(tmp_path):
    db_ok = _setup_db(tmp_path / "ok.db", True)
    assert run(db_ok, 0.8)
    db_bad = _setup_db(tmp_path / "bad.db", False)
    assert not run(db_bad, 0.8)
