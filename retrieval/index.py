"""Vector index backed by FAISS when available."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np


class VectorIndex:
    """Simple vector similarity index.

    Uses FAISS for efficient similarity search if the library is installed. If
    FAISS is unavailable, falls back to a minimal ``numpy`` implementation which
    is sufficient for unit tests and small in-memory datasets.
    """

    def __init__(self, dim: int) -> None:
        self.dim = dim
        try:  # pragma: no cover - optional dependency
            import faiss  # type: ignore[import]

            self._index = faiss.IndexFlatIP(dim)
            self._use_faiss = True
        except Exception:  # pragma: no cover - library missing
            self._index = None
            self._use_faiss = False
            self._vectors = np.empty((0, dim), dtype=np.float32)
        self._meta: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    def add(self, vectors: np.ndarray, metadatas: List[Dict[str, Any]]) -> None:
        if vectors.shape[1] != self.dim:
            raise ValueError("dimension mismatch")
        if self._use_faiss:
            self._index.add(vectors)
        else:
            self._vectors = np.vstack([self._vectors, vectors])
        self._meta.extend(metadatas)

    # ------------------------------------------------------------------
    def search(
        self, query: np.ndarray, top_k: int = 5
    ) -> List[Tuple[Dict[str, Any], float]]:
        if query.shape[1] != self.dim:
            raise ValueError("dimension mismatch")
        if self._use_faiss:
            scores, idxs = self._index.search(query, top_k)
            results: List[Tuple[Dict[str, Any], float]] = []
            for i, score in zip(idxs[0], scores[0]):
                if i == -1 or i >= len(self._meta):
                    continue
                results.append((self._meta[i], float(score)))
            return results
        sims = self._vectors @ query[0]
        best = sims.argsort()[::-1][:top_k]
        return [(self._meta[i], float(sims[i])) for i in best]

    # ------------------------------------------------------------------
    def reset(self) -> None:
        self._meta.clear()
        if self._use_faiss:
            self._index.reset()
        else:
            self._vectors = np.empty((0, self.dim), dtype=np.float32)
