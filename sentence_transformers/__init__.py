import hashlib
from typing import Sequence

import numpy as np


class SentenceTransformer:  # pragma: no cover - simple offline stub
    def __init__(self, model_name: str):
        self.model_name = model_name
        self._dim = 384

    def encode(self, texts: Sequence[str], convert_to_numpy: bool = True) -> np.ndarray:
        vectors: list[np.ndarray] = []
        for text in texts:
            vec = np.zeros(self._dim, dtype=np.float32)
            for token in text.lower().split():
                idx = (
                    int.from_bytes(hashlib.md5(token.encode("utf-8")).digest(), "big")
                    % self._dim
                )
                vec[idx] += 1.0
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec /= norm
            vectors.append(vec)
        return np.vstack(vectors)

    def get_sentence_embedding_dimension(self) -> int:
        return self._dim
