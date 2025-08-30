from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Iterable, List

_CTRL_RE = re.compile(r"[\u0000-\u001F\u007F]")
_WS_RE = re.compile(r"\s+")


def normalize_text(s: str) -> str:
    """Normalize text for stable hashing and chunking.

    - Unicode NFC
    - drop control chars
    - replace soft hyphen and common ligatures
    - collapse whitespace
    """
    s = s.replace("\u00ad", "")  # soft hyphen
    s = s.replace("\ufb01", "fi").replace("\ufb02", "fl")  # ligatures
    s = unicodedata.normalize("NFC", s)
    s = _CTRL_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def _approx_tokenize(s: str) -> List[str]:
    return [t for t in re.split(r"\s+", s) if t]


def token_len(s: str) -> int:
    try:  # optional dependency
        import tiktoken  # type: ignore[import-not-found]

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(s))
    except Exception:
        return len(_approx_tokenize(s))


def chunk_by_tokens(text: str, target: int, overlap: int) -> List[str]:
    """Split text by approximate token windows with overlap.

    Simple whitespace tokenization fallback when tiktoken missing.
    """
    toks = _approx_tokenize(text)
    if not toks:
        return []
    chunks: List[str] = []
    i = 0
    step = max(1, target - overlap)
    while i < len(toks):
        part = toks[i : i + target]
        chunks.append(" ".join(part))
        if i + target >= len(toks):
            break
        i += step
    return chunks


def simhash64(text: str) -> int:
    """Compute a 64-bit simhash using word 3-grams.

    Lightweight implementation suitable for near-duplicate detection.
    """
    words = _approx_tokenize(normalize_text(text).lower())
    if not words:
        return 0
    vec = [0] * 64
    for i in range(len(words) - 2):
        gram = " ".join(words[i : i + 3])
        h = int.from_bytes(hashlib.sha256(gram.encode("utf-8")).digest()[:8], "big")
        for bit in range(64):
            if h >> bit & 1:
                vec[bit] += 1
            else:
                vec[bit] -= 1
    out = 0
    for bit in range(64):
        if vec[bit] >= 0:
            out |= 1 << bit
    return out


__all__ = ["normalize_text", "token_len", "chunk_by_tokens", "simhash64"]
