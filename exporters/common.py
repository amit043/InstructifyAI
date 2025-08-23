from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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


@dataclass
class SplitSpec:
    """Specification for applying train/val/test splits to exports.

    Attributes:
        strategy: Currently only ``"stratified"`` is supported.
        by: List of metadata fields to stratify on.
        fractions: Mapping of split name to desired fraction.
        seed: Optional random seed to ensure determinism.
        tolerance: Allowed deviation in fraction per split.
    """

    strategy: str = "stratified"
    by: List[str] = field(default_factory=list)
    fractions: Dict[str, float] = field(
        default_factory=lambda: {"train": 0.8, "test": 0.2}
    )
    seed: Optional[int] = None
    tolerance: float = 0.03


@dataclass
class DedupeOptions:
    """Options controlling near-duplicate filtering during export."""

    drop_near_dupes: bool = False
    dupe_threshold: float = 0.85


__all__ = ["ExportChunk", "SplitSpec", "DedupeOptions"]
