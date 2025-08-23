from __future__ import annotations

"""Utility to write Parquet bytes using pyarrow."""

import io
from typing import Any, Dict, List


def write_parquet(rows: List[Dict[str, Any]]) -> bytes:
    """Return Parquet representation of row dicts.

    Column order is deterministic (sorted by key).
    """
    import pyarrow as pa  # type: ignore[import-not-found, import-untyped]
    import pyarrow.parquet as pq  # type: ignore[import-not-found, import-untyped]

    if rows:
        keys = sorted({k for row in rows for k in row.keys()})
        columns = {k: [row.get(k) for row in rows] for k in keys}
        table = pa.table(columns)
    else:  # pragma: no cover - defensive, empty export
        table = pa.table({})
    buf = io.BytesIO()
    pq.write_table(table, buf)
    return buf.getvalue()


__all__ = ["write_parquet"]
