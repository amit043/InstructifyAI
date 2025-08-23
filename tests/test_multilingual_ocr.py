import io
import json
import uuid

import pytest
from PIL import Image, ImageDraw

pytest.importorskip("fitz")
pytest.importorskip("pytesseract")
pytest.importorskip("langdetect")

from typing import cast

import fitz  # type: ignore[import-not-found, import-untyped]
import pytesseract  # type: ignore[import-untyped]

from chunking.chunker import Block as ChunkBlock
from chunking.chunker import chunk_blocks
from core.lang_detect import detect_lang
from parsers.pdf_v2 import PDFParserV2
from storage.object_store import derived_key
from worker.derived_writer import upsert_chunks
from worker.ocr.config import tesseract_lang_string


def _tesseract_available() -> bool:
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _tesseract_available(), reason="tesseract not installed")
def test_multilingual_ocr_manifest(test_app) -> None:
    doc = fitz.open()

    page1 = doc.new_page()
    page1.insert_text((72, 72), "HELLO world")

    page2 = doc.new_page()
    img = Image.new("RGB", (300, 40), "white")
    draw = ImageDraw.Draw(img)
    draw.text((5, 5), "HALLO WELT HALLO WELT", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    page2.insert_image(fitz.Rect(0, 0, 300, 40), stream=buf.getvalue())

    pdf_bytes = doc.tobytes()
    doc.close()

    parser = PDFParserV2(langs=["eng", "deu"])
    blocks = list(parser.parse(pdf_bytes))

    assert detect_lang("hello world") == "en"
    assert tesseract_lang_string(["eng", "deu", "eng"]) == "eng+deu"

    assert parser.page_metrics[0].lang == "en"
    assert parser.page_metrics[1].lang == "de"
    assert parser.langs_used == ["de", "en"]

    cb_blocks = []
    for b in blocks:
        meta = {}
        if "lang" in b.meta:
            meta["lang"] = b.meta["lang"]
        if "source_stage" in b.meta:
            meta["source_stage"] = b.meta["source_stage"]
        cb_blocks.append(
            ChunkBlock(text=b.text, page=cast(int, b.meta["page"]), metadata=meta)
        )
    chunks = chunk_blocks(cb_blocks)

    _, store, _, SessionLocal = test_app
    with SessionLocal() as db:
        doc_id = str(uuid.uuid4())
        upsert_chunks(db, store, doc_id=doc_id, version=1, chunks=chunks)

    manifest = json.loads(store.client.store[derived_key(doc_id, "manifest.json")])
    assert manifest["page_langs"] == ["en", "de"]
    assert manifest["langs_used"] == ["de", "en"]
