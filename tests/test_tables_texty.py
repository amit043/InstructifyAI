import os

import pytest

from chunking.chunker import chunk_blocks
from core.settings import get_settings
from parsers import registry

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
    chunks = chunk_blocks(blocks, min_tokens=1, max_tokens=10)
    table_chunk = next(c for c in chunks if c.content.type == "table_text")
    assert table_chunk.content.text == "A\tB\nC\tD"


def _make_pdf_with_table() -> bytes:
    import fitz  # type: ignore[import-not-found]

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
    assert any(b.type == "table_text" for b in blocks)
