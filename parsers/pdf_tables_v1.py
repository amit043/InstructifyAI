from __future__ import annotations

import fitz  # type: ignore[import-not-found, import-untyped]

from chunking.chunker import Block


def extract_table_blocks(
    page: fitz.Page, page_index: int, section_path: list[str]
) -> list[Block]:
    blocks: list[Block] = []
    try:
        tables = page.find_tables()
    except Exception:  # pragma: no cover - if find_tables not available
        return blocks
    for table in getattr(tables, "tables", []):
        rows = table.extract()
        tsv_rows = ["\t".join(cell or "" for cell in row) for row in rows]
        text = "\n".join(tsv_rows)
        blocks.append(
            Block(
                text=text,
                type="table_text",
                page=page_index,
                section_path=section_path.copy(),
            )
        )
    return blocks


__all__ = ["extract_table_blocks"]
