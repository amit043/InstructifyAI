from __future__ import annotations

import hashlib
from typing import Iterable


def sha256_bytes(data: bytes) -> str:
    """Return the SHA-256 hex digest for given bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_str(text: str) -> str:
    """Return the SHA-256 hex digest for a UTF-8 string."""
    return sha256_bytes(text.encode("utf-8"))


def stable_chunk_key(section_path: Iterable[str], text: str) -> str:
    """Compute stable key combining section path and text."""
    path = "/".join(section_path)
    return sha256_str(path + text)


__all__ = ["sha256_bytes", "sha256_str", "stable_chunk_key"]
