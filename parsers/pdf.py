from __future__ import annotations

import fitz  # type: ignore[import-not-found, import-untyped]

from chunking.chunker import Block

from .registry import registry


@registry.register("pdf")
def parse_pdf(data: bytes):
    doc = fitz.open(stream=data, filetype="pdf")
    current_heading: list[str] = []
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
                yield Block(
                    text=line, page=page_index, section_path=current_heading.copy()
                )
