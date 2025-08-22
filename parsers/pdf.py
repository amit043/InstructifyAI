from __future__ import annotations

import fitz  # type: ignore[import-not-found, import-untyped]

from chunking.chunker import Block
from core.settings import get_settings

from .pdf_tables_v1 import extract_table_blocks
from .registry import Parser, registry


@registry.register("application/pdf")
class PDFParser:
    @staticmethod
    def parse(data: bytes):
        doc = fitz.open(stream=data, filetype="pdf")
        current_heading: list[str] = []
        first_block = True
        tables_enabled = get_settings().tables_as_text
        for page_index, page in enumerate(doc, start=1):
            for block in page.get_text("blocks"):
                text = block[4].strip()
                if not text:
                    continue
                for line in text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.isupper():
                        current_heading = [line]
                    elif first_block and not current_heading:
                        current_heading = ["INTRO"]
                    yield Block(
                        text=line, page=page_index, section_path=current_heading.copy()
                    )
                    first_block = False
            if tables_enabled:
                for tbl in extract_table_blocks(page, page_index, current_heading):
                    yield tbl


__all__ = ["PDFParser"]
