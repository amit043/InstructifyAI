import json
from typing import List

from models import Document, Taxonomy
from storage.object_store import derived_key, export_key
from tests.conftest import PROJECT_ID_1


def _add_taxonomy(SessionLocal) -> None:
    with SessionLocal() as session:
        session.add(Taxonomy(project_id=PROJECT_ID_1, version=1, fields=[]))
        session.commit()


def _put_doc(store, session, doc_id: str, severity: str, texts: List[str]) -> None:
    session.add(Document(id=doc_id, project_id=PROJECT_ID_1, source_type="pdf"))
    lines = []
    for idx, text in enumerate(texts):
        chunk = {
            "doc_id": doc_id,
            "chunk_id": f"{doc_id}-c{idx}",
            "order": idx,
            "rev": 1,
            "content": {"type": "text", "text": text},
            "source": {"page": 1, "section_path": ["S"]},
            "text_hash": "h",
            "metadata": {"severity": severity},
        }
        lines.append(json.dumps(chunk))
    store.put_bytes(
        derived_key(doc_id, "chunks.jsonl"),
        ("\n".join(lines) + "\n").encode("utf-8"),
    )


def test_stratified_split(test_app) -> None:
    client, store, _, SessionLocal = test_app
    _add_taxonomy(SessionLocal)
    with SessionLocal() as session:
        _put_doc(store, session, "d1", "high", ["a", "b"])
        _put_doc(store, session, "d2", "high", ["c", "d"])
        _put_doc(store, session, "d3", "low", ["e", "f"])
        _put_doc(store, session, "d4", "low", ["g", "h"])
        session.commit()
    template = '{{ {"doc_id": chunk.doc_id, "split": chunk.metadata.split} | tojson }}'
    resp = client.post(
        "/export/jsonl",
        json={
            "project_id": str(PROJECT_ID_1),
            "doc_ids": ["d1", "d2", "d3", "d4"],
            "template": template,
            "split": {
                "strategy": "stratified",
                "by": ["severity"],
                "fractions": {"train": 0.5, "test": 0.5},
                "seed": 42,
            },
        },
        headers={"X-Role": "curator"},
    )
    assert resp.status_code == 200
    data = resp.json()
    key = export_key(data["export_id"], "data.jsonl")
    lines = store.get_bytes(key).decode("utf-8").strip().splitlines()
    parsed = [json.loads(l) for l in lines]
    doc_splits: dict[str, str] = {}
    for row in parsed:
        doc_splits.setdefault(row["doc_id"], row["split"])
        assert doc_splits[row["doc_id"]] == row["split"]
    # each severity should appear once per split
    sev_map = {"d1": "high", "d2": "high", "d3": "low", "d4": "low"}
    counts = {"high": {"train": 0, "test": 0}, "low": {"train": 0, "test": 0}}
    for doc_id, split in doc_splits.items():
        counts[sev_map[doc_id]][split] += 1
    assert counts["high"] == {"train": 1, "test": 1}
    assert counts["low"] == {"train": 1, "test": 1}
    manifest = json.loads(
        store.get_bytes(export_key(data["export_id"], "manifest.json")).decode("utf-8")
    )
    assert manifest["split_stats"] == {"train": 4, "test": 4}
