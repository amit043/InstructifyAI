from __future__ import annotations

from bs4 import Tag  # type: ignore[import-untyped]


def table_to_tsv(table: Tag) -> str:
    """Convert an HTML <table> to TSV string."""
    rows: list[str] = []
    for tr in table.find_all("tr"):  # type: ignore[union-attr]
        cells = [
            c.get_text(" ", strip=True)
            for c in tr.find_all(["th", "td"])  # type: ignore[union-attr]
        ]
        rows.append("\t".join(cells))
    return "\n".join(rows)


__all__ = ["table_to_tsv"]
