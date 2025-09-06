"""Semantic search API endpoints."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter
from pydantic import BaseModel

from retrieval.embeddings import EmbeddingModel
from retrieval.index import VectorIndex

router = APIRouter()

_model = EmbeddingModel()
_index = VectorIndex(dim=_model.dim)


class IndexChunk(BaseModel):
    id: str
    text: str


class SearchResponseItem(BaseModel):
    id: str
    text: str
    score: float


@router.post("/search/index")
def index_chunks(chunks: List[IndexChunk]) -> dict[str, int]:
    texts = [c.text for c in chunks]
    vectors = _model.embed(texts)
    _index.reset()
    _index.add(vectors, [c.model_dump() for c in chunks])
    return {"indexed": len(chunks)}


@router.get("/search", response_model=List[SearchResponseItem])
def search(q: str, top_k: int = 5) -> List[SearchResponseItem]:
    vectors = _model.embed([q])
    results = _index.search(vectors, top_k=top_k)
    return [
        SearchResponseItem(id=r["id"], text=r["text"], score=score)
        for r, score in results
    ]
