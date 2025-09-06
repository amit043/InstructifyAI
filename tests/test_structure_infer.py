import pathlib

import pytest

from parser_pipeline.structure import structure

BASE = pathlib.Path(__file__).resolve().parent.parent


def _load(path: str) -> bytes:
    return (BASE / path).read_bytes()


def test_html_structure_titles_and_tables() -> None:
    pytest.importorskip("bs4")
    data = _load("examples/golden/sample.html")
    blocks = list(structure(data, source_type="text/html"))
    assert blocks[0].metadata.get("kind") == "title"
    assert blocks[0].section_path == ["Title"]
    table_block = next(b for b in blocks if b.type == "table_placeholder")
    assert table_block.section_path == ["Title", "Section A"]


def test_pdf_structure_titles() -> None:
    pytest.importorskip("fitz")
    data = _load("examples/golden/sample.pdf")
    blocks = list(structure(data, source_type="application/pdf"))
    assert blocks[0].metadata.get("kind") == "title"
    assert blocks[0].section_path == [blocks[0].text]
