import hashlib
import uuid

from models import Document, DocumentStatus, DocumentVersion
from parser_pipeline.normalize import normalize
from parser_pipeline.preflight import preflight
from tests.conftest import PROJECT_ID_1


def _create_doc(db, data: bytes) -> DocumentVersion:
    doc_id = str(uuid.uuid4())
    dv_id = str(uuid.uuid4())
    doc = Document(
        id=doc_id, project_id=PROJECT_ID_1, source_type="txt", latest_version_id=dv_id
    )
    dv = DocumentVersion(
        id=dv_id,
        document_id=doc_id,
        project_id=PROJECT_ID_1,
        version=1,
        doc_hash=hashlib.sha256(data).hexdigest(),
        mime="application/octet-stream",
        size=len(data),
        status=DocumentStatus.INGESTED.value,
        meta={},
    )
    db.add_all([doc, dv])
    db.commit()
    return dv


def test_preflight_detects_non_utf8_and_records_metric(test_app) -> None:
    _, _, _, SessionLocal = test_app
    data = ("Caf\xe9 " * 3).encode("latin-1")
    with SessionLocal() as db:
        dv = _create_doc(db, data)
        res = preflight(db, dv, data, "x.txt")
        assert res.encoding.lower() != "utf-8"
        assert dv.meta["parse"]["non_utf8_ratio"] > 0
        text = normalize(db, dv, data, res.encoding)
        assert "Café" in text
        assert dv.meta["parse"].get("control_char_count", 0) == 0


def test_normalize_strips_controls_and_nfkc(test_app) -> None:
    _, _, _, SessionLocal = test_app
    raw = "Line1\rLine2\x00\tLine3\x1fLigature: ﬁ".encode("utf-8")
    with SessionLocal() as db:
        dv = _create_doc(db, raw)
        res = preflight(db, dv, raw, "y.txt")
        text = normalize(db, dv, raw, res.encoding)
        assert text == "Line1\nLine2\tLine3Ligature: fi"
        assert dv.meta["parse"]["control_char_count"] == 2
        assert dv.meta["parse"].get("non_utf8_ratio", 0) == 0
