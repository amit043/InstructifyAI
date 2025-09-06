import json

import sqlalchemy as sa

from storage.object_store import derived_key
from tests.conftest import PROJECT_ID_1


def _setup_worker(store, SessionLocal):
    from worker import main as worker_main

    worker_main.create_client = lambda **kwargs: store.client
    worker_main.settings.s3_bucket = store.bucket
    worker_main.SessionLocal = SessionLocal
    # Force page OCR fallback by requiring long minimum text length
    worker_main.settings.min_text_len_for_ocr = 100


def test_pdf_native_and_image_ocr_fused(test_app, monkeypatch) -> None:
    client, store, _calls, SessionLocal = test_app
    _setup_worker(store, SessionLocal)

    # Mock fitz (PyMuPDF) used by parsers.pdf_parser
    import parsers.pdf_parser as pdfp

    class FakeRect:
        def __init__(self):
            self.width = 100.0
            self.height = 200.0

    class FakePage:
        def __init__(self):
            self.rect = FakeRect()

        def get_text(self, kind):  # noqa: ANN001
            if kind == "text":
                return "Hello world"
            if kind == "rawdict":
                return {
                    "blocks": [
                        {
                            "type": 1,
                            "bbox": [10.0, 20.0, 50.0, 80.0],
                            "image": {"xref": 1},
                        }
                    ]
                }
            return ""

        def get_pixmap(self, dpi=300):  # noqa: ANN001
            class Pix:
                def tobytes(self, fmt):  # noqa: ANN001
                    return b"PAGEPNG"

            return Pix()

    class FakePDF:
        def __iter__(self):
            yield FakePage()

    class FakeFitz:
        class Pixmap:
            def __init__(self, pdf, xref):  # noqa: ANN001
                pass

            def tobytes(self, fmt):  # noqa: ANN001
                return b"IMGPNG"

        @staticmethod
        def open(stream, filetype):  # noqa: ANN001
            return FakePDF()

    monkeypatch.setattr(pdfp, "fitz", FakeFitz)

    # Mock OCR to return recognisable strings
    def fake_ocr(img_bytes, langs):  # noqa: ANN001
        if img_bytes == b"IMGPNG":
            return "image ocr text"
        return "page ocr text"

    monkeypatch.setattr(pdfp, "ocr_page", fake_ocr)

    # Ingest a fake PDF (bytes content not used by mocked fitz)
    resp = client.post(
        "/ingest",
        data={"project_id": str(PROJECT_ID_1)},
        files={"file": ("sample.pdf", b"%PDF-1.4\n...", "application/pdf")},
        headers={"X-Role": "viewer"},
    )
    assert resp.status_code == 200
    doc_id = resp.json()["doc_id"]

    # Run parse synchronously
    from worker import main as worker_main

    worker_main.parse_document(doc_id, 1)

    # Validate chunks.jsonl contains image + text + page-ocr entries
    data = store.get_bytes(derived_key(doc_id, "chunks.jsonl")).decode("utf-8").strip()
    lines = [json.loads(l) for l in data.splitlines() if l.strip()]
    types = [l.get("content", {}).get("type") for l in lines]
    stages = [l.get("metadata", {}).get("source_stage") for l in lines]

    # Expect one image chunk from image OCR
    assert "image" in types
    img_idx = types.index("image")
    img = lines[img_idx]
    assert img["content"].get("image_key")
    assert img["metadata"].get("source_stage") == "image_ocr"
    bbox = img["metadata"].get("bbox")
    assert all(0.0 <= v <= 1.0 for v in bbox)

    # Expect native text chunk and page-ocr fallback
    assert stages.count("pdf_text") >= 1
    assert stages.count("pdf_ocr") >= 1

