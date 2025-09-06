"""Simple embedding utilities with optional SentenceTransformer backend."""

from __future__ import annotations

import hashlib
from typing import Sequence

import numpy as np

try:  # pragma: no cover - optional dependency
    from sentence_transformers import SentenceTransformer  # type: ignore[import]
except Exception:  # pragma: no cover - library missing
    SentenceTransformer = None  # type: ignore[misc, assignment]


class EmbeddingModel:
    """Configurable embedding model.

    Attempts to use ``sentence-transformers`` if available, falling back to a
    deterministic hashed bag-of-words representation. The fallback keeps tests
    lightweight while still exercising the vector index.
    """

    def __init__(self, model_name: str | None = None, dim: int = 384) -> None:
        self.model_name = model_name or "sentence-transformers/all-MiniLM-L6-v2"
        self.dim = dim
        self._model = None
        self._use_sentence_transformer = False
        if SentenceTransformer is not None:  # pragma: no cover - optional
            self._model = SentenceTransformer(self.model_name)
            self.dim = int(self._model.get_sentence_embedding_dimension())
            self._use_sentence_transformer = True

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Return embeddings for ``texts`` as a 2D ``numpy`` array."""

        if (
            self._use_sentence_transformer and self._model is not None
        ):  # pragma: no cover - optional
            return np.asarray(self._model.encode(list(texts), convert_to_numpy=True))
        return self._hash_embed(texts)

    # ------------------------------------------------------------------
    # Fallback embedding based on hashed bag-of-words. Deterministic and
    # lightweight, suitable for unit tests where heavyweight models are
    # unavailable.
    # ------------------------------------------------------------------
    def _hash_embed(self, texts: Sequence[str]) -> np.ndarray:
        vectors: list[np.ndarray] = []
        for text in texts:
            vec = np.zeros(self.dim, dtype=np.float32)
            for token in text.lower().split():
                idx = (
                    int.from_bytes(hashlib.md5(token.encode("utf-8")).digest(), "big")
                    % self.dim
                )
                vec[idx] += 1.0
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec /= norm
            vectors.append(vec)
        return np.vstack(vectors)
