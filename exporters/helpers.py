from __future__ import annotations

from datetime import date, datetime
from typing import Mapping, Sequence


def join_section_path(meta: Mapping[str, Sequence[str] | None]) -> str:
    """Join a section path list into a string."""
    path = meta.get("section_path") or []
    return " / ".join(path)


def iso8601(dt: datetime | date) -> str:
    """Return ISO-8601 string for date or datetime."""
    return dt.isoformat()


__all__ = ["join_section_path", "iso8601"]
