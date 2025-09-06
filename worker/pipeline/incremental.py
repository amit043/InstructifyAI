from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Tuple

from chunking.chunker import Block
from core.hash import sha256_str


def hash_parts(blocks: Iterable[Block]) -> Dict[str, str]:
    """Return a mapping of part identifier to hash."""
    by_part: dict[str, List[str]] = defaultdict(list)
    for blk in blocks:
        if blk.metadata.get("file_path"):
            key = blk.metadata["file_path"]
        elif blk.page is not None:
            key = str(blk.page)
        else:
            continue
        if blk.text:
            by_part[key].append(blk.text)
    return {k: sha256_str("".join(v)) for k, v in by_part.items()}


def plan_deltas(
    blocks: Iterable[Block], previous: Dict[str, str]
) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """Compute new part hashes and delta vs previous mapping."""
    current = hash_parts(blocks)
    added = [k for k in current.keys() - previous.keys()]
    removed = [k for k in previous.keys() - current.keys()]
    changed = [k for k in current.keys() & previous.keys() if previous[k] != current[k]]
    deltas = {
        "added": sorted(added),
        "removed": sorted(removed),
        "changed": sorted(changed),
    }
    return current, deltas


__all__ = ["hash_parts", "plan_deltas"]
