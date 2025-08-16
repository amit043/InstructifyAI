from chunking.chunker import Block, chunk_blocks
from core.metrics import compute_curation_completeness
from tests.conftest import PROJECT_ID_1
from worker.derived_writer import upsert_chunks


def test_curation_completeness_metric(test_app) -> None:
    client, store, _, SessionLocal = test_app
    payload = {
        "fields": [
            {
                "name": "severity",
                "type": "enum",
                "required": True,
                "options": ["low", "high"],
            }
        ]
    }
    client.put(
        f"/projects/{PROJECT_ID_1}/taxonomy",
        json=payload,
        headers={"X-Role": "curator"},
    )
    resp = client.post(
        "/ingest",
        data={"project_id": str(PROJECT_ID_1)},
        files={"file": ("doc.txt", b"hello", "text/plain")},
    )
    doc_id = resp.json()["doc_id"]
    blocks = [Block(text="a", page=1), Block(text="b", page=1)]
    chunks = chunk_blocks(blocks, min_tokens=1, max_tokens=1)
    chunks[0].metadata = {"severity": "high"}
    chunks[1].metadata = {"severity": ""}
    with SessionLocal() as db:
        upsert_chunks(db, store, doc_id=doc_id, version=1, chunks=chunks)
        comp = compute_curation_completeness(doc_id, PROJECT_ID_1, 1, db)
    assert comp == 0.5
    resp_metrics = client.get(f"/documents/{doc_id}/metrics")
    assert resp_metrics.status_code == 200
    assert resp_metrics.json()["curation_completeness"] == 0.5
