from __future__ import annotations

import fitz  # type: ignore[import-not-found, import-untyped]

from chunking.chunker_v2 import Block


def extract_table_blocks(
    page: fitz.Page,
    page_index: int,
    section_path: list[str],
    table_id_start: int,
) -> tuple[list[Block], int]:
    blocks: list[Block] = []
    next_id = table_id_start
    try:
        tables = page.find_tables()
    except Exception:  # pragma: no cover - if find_tables not available
        return blocks, next_id
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
                metadata={"table_id": next_id},
            )
        )
        next_id += 1
    return blocks, next_id


__all__ = ["extract_table_blocks"]
