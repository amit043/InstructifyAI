import time

from fastapi.testclient import TestClient

from api.main import app
from retrieval.embeddings import EmbeddingModel
from retrieval.index import VectorIndex


def _sample_chunks() -> list[dict[str, str]]:
    return [
        {"id": "1", "text": "The cat sat on the mat."},
        {"id": "2", "text": "Dogs are wonderful pets."},
        {"id": "3", "text": "The quick brown fox jumps over the lazy dog."},
    ]


def test_vector_index_search() -> None:
    model = EmbeddingModel()
    index = VectorIndex(dim=model.dim)
    chunks = _sample_chunks()
    vectors = model.embed([c["text"] for c in chunks])
    index.add(vectors, chunks)
    query_vec = model.embed(["cat on mat"])
    start = time.perf_counter()
    results = index.search(query_vec, top_k=1)
    elapsed = time.perf_counter() - start
    assert results[0][0]["id"] == "1"
    assert elapsed < 0.2


def test_search_api() -> None:
    client = TestClient(app)
    chunks = _sample_chunks()
    client.post("/search/index", json=chunks)
    start = time.perf_counter()
    resp = client.get("/search", params={"q": "cat on mat", "top_k": 1})
    elapsed = time.perf_counter() - start
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["id"] == "1"
    assert elapsed < 0.2
