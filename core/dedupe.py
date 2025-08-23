from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Dict, List, Sequence, Tuple

from ops.metrics import dedupe_drop_percent


def _simhash(text: str) -> int:
    """Return 64-bit SimHash for given text."""
    v = [0] * 64
    for token in text.split():
        h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
        for i in range(64):
            v[i] += 1 if h & (1 << i) else -1
    result = 0
    for i, val in enumerate(v):
        if val > 0:
            result |= 1 << i
    return result


def _minhash(tokens: Sequence[str], num_perm: int = 64) -> List[int]:
    """Return MinHash signature for the given tokens."""
    sig: List[int] = []
    for i in range(num_perm):
        min_val: int | None = None
        for token in tokens:
            h = hashlib.sha1(f"{token}-{i}".encode("utf-8")).hexdigest()
            val = int(h, 16)
            if min_val is None or val < min_val:
                min_val = val
        sig.append(min_val or 0)
    return sig


def _jaccard(sig1: Sequence[int], sig2: Sequence[int]) -> float:
    """Approximate Jaccard similarity between two MinHash signatures."""
    if not sig1 or not sig2 or len(sig1) != len(sig2):
        return 0.0
    matches = sum(1 for a, b in zip(sig1, sig2) if a == b)
    return matches / len(sig1)


def drop_near_duplicates(
    chunks: List[dict], threshold: float = 0.85
) -> Tuple[List[dict], Dict[str, int]]:
    """Drop near-duplicate chunks using SimHash + LSH.

    Returns filtered chunks and stats {input, dropped, kept}.
    """
    if not chunks:
        return [], {"input": 0, "dropped": 0, "kept": 0}
    bands = 8
    rows = 8
    tables: List[Dict[int, List[Tuple[int, List[int]]]]] = [
        defaultdict(list) for _ in range(bands)
    ]
    max_ham = int(64 * (1 - threshold))
    kept: List[dict] = []
    dropped = 0
    for ch in chunks:
        text = ch.get("content", {}).get("text", "")
        tokens = text.split()
        sig = _simhash(text)
        min_sig = _minhash(tokens)
        is_dupe = False
        for b in range(bands):
            start = b * rows
            key = (sig >> start) & 0xFF
            for other_sig, other_min in tables[b].get(key, []):
                if (
                    bin(other_sig ^ sig).count("1") <= max_ham
                    and _jaccard(other_min, min_sig) >= threshold
                ):
                    is_dupe = True
                    break
            if is_dupe:
                break
        if is_dupe:
            dropped += 1
            continue
        kept.append(ch)
        for b in range(bands):
            start = b * rows
            key = (sig >> start) & 0xFF
            tables[b][key].append((sig, min_sig))
    stats = {"input": len(chunks), "dropped": dropped, "kept": len(kept)}
    if stats["input"]:
        dedupe_drop_percent.set(100.0 * stats["dropped"] / stats["input"])
    else:
        dedupe_drop_percent.set(0.0)
    return kept, stats


__all__ = ["drop_near_duplicates"]
