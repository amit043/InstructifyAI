import json
import os

import pytest

from chunking.chunker_v2 import chunk_blocks
from core.settings import get_settings
from parsers import registry
from storage.object_store import derived_key, export_key
from tests.conftest import PROJECT_ID_1
from tests.test_exporters import _add_taxonomy

pytest.importorskip("bs4")


def _enable_tables_as_text() -> None:
    os.environ["TABLES_AS_TEXT"] = "1"
    get_settings.cache_clear()  # type: ignore[attr-defined]
    get_settings()


def test_html_table_to_text() -> None:
    _enable_tables_as_text()
    html = (
        "<html><body><h1>Title</h1><table><tr><td>A</td><td>B</td></tr>"
        "<tr><td>C</td><td>D</td></tr></table></body></html>"
    )
    blocks = list(registry.get("text/html").parse(html.encode()))
    table_block = next(b for b in blocks if b.type == "table_text")
    assert table_block.text == "A\tB\nC\tD"
    assert table_block.metadata["table_id"] == 0
    chunks = chunk_blocks(blocks, max_tokens=2)  # type: ignore[arg-type]
    table_chunks = [c for c in chunks if c.content.type == "table_text"]
    assert table_chunks[0].metadata["table_id"] == 0
    assert table_chunks[0].content.text and table_chunks[0].content.text.startswith(
        "A\tB"
    )


def _make_pdf_with_table() -> bytes:
    import fitz  # type: ignore[import-not-found, import-untyped]

    doc = fitz.open()
    page = doc.new_page()
    for i in range(3):
        y = 50 + i * 50
        page.draw_line((50, y), (150, y))
        x = 50 + i * 50
        page.draw_line((x, 50), (x, 150))
    page.insert_text((60, 80), "a")
    page.insert_text((110, 80), "b")
    page.insert_text((60, 130), "c")
    page.insert_text((110, 130), "d")
    return doc.tobytes()


def test_pdf_table_to_text() -> None:
    pytest.importorskip("fitz")
    _enable_tables_as_text()
    data = _make_pdf_with_table()
    blocks = list(registry.get("application/pdf").parse(data))
    tbl = next(b for b in blocks if b.type == "table_text")
    assert tbl.metadata["table_id"] == 0


def test_manifest_counts_tables(test_app) -> None:
    client, store, _, SessionLocal = test_app
    _add_taxonomy(SessionLocal)
    chunk = {
        "doc_id": "d1",
        "chunk_id": "c1",
        "order": 0,
        "rev": 1,
        "content": {"type": "table_text", "text": "a\tb"},
        "metadata": {"table_id": 5},
        "text_hash": "h",
    }
    store.put_bytes(
        derived_key("d1", "chunks.jsonl"),
        (json.dumps(chunk) + "\n").encode("utf-8"),
    )
    resp = client.post(
        "/export/jsonl",
        json={
            "project_id": str(PROJECT_ID_1),
            "doc_ids": ["d1"],
            "template": "{{ chunk.content.text }}",
        },
        headers={"X-Role": "curator"},
    )
    assert resp.status_code == 200
    export_id = resp.json()["export_id"]
    manifest = json.loads(
        store.get_bytes(export_key(export_id, "manifest.json")).decode("utf-8")
    )
    assert manifest["table_count"] == 1
