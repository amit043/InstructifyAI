from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ExportChunk:
    """Lightweight chunk model used by exporters.

    Step information, when available, is stored in ``metadata['step_id']``
    and exposed via the :attr:`step_id` property.
    """

    doc_id: str
    chunk_id: str
    order: int
    content: Dict[str, Any]
    source: Dict[str, Any]
    text_hash: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def step_id(self) -> Optional[int]:
        return self.metadata.get("step_id")


__all__ = ["ExportChunk"]
