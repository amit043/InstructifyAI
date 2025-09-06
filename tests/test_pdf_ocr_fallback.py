from __future__ import annotations

import json
import pathlib

import pytest

pytest.importorskip("fitz")
pytest.importorskip("pytesseract")

from parsers import registry
from storage.object_store import derived_key
from tests.conftest import PROJECT_ID_1
from worker import main as worker_main

BASE = pathlib.Path(__file__).resolve().parent


def _setup_worker(store, SessionLocal):
    worker_main.create_client = lambda **kwargs: store.client
    worker_main.settings.s3_bucket = store.bucket
    worker_main.SessionLocal = SessionLocal


def _tesseract_available() -> bool:
    try:
        import pytesseract  # type: ignore

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _tesseract_available(), reason="tesseract not installed")
def test_pdf_ocr_fallback(test_app) -> None:
    client, store, _, SessionLocal = test_app
    _setup_worker(store, SessionLocal)
    pdf_bytes = (BASE / "fixtures" / "image_ocr.pdf").read_bytes()

    # Parser without OCR extracts no text
    blocks = list(registry.get("application/pdf").parse(pdf_bytes))
    assert sum(len(b.text.strip()) for b in blocks) == 0

    resp = client.post(
        "/ingest",
        data={"project_id": str(PROJECT_ID_1)},
        files={"file": ("image.pdf", pdf_bytes, "application/pdf")},
    )
    doc_id = resp.json()["doc_id"]

    worker_main.parse_document(doc_id, 1)

    chunk_lines = (
        (store.client.store[derived_key(doc_id, "chunks.jsonl")].decode("utf-8"))
        .strip()
        .splitlines()
    )
    texts = [
        json.loads(line)["text"] for line in chunk_lines if json.loads(line).get("text")
    ]
    assert any(t.strip() for t in texts)
    first_meta = json.loads(chunk_lines[0])["meta"]
    assert first_meta["source_stage"] == "pdf_ocr"

    manifest = json.loads(store.client.store[derived_key(doc_id, "manifest.json")])
    assert manifest["pages_ocr"] == [1]
