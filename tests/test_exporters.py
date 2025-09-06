import json
from typing import List

from models import Taxonomy
from storage.object_store import derived_key, export_key
from tests.conftest import PROJECT_ID_1


def _add_taxonomy(SessionLocal) -> None:
    with SessionLocal() as session:
        session.add(Taxonomy(project_id=PROJECT_ID_1, version=1, fields=[]))
        session.commit()


def _put_chunk(store, doc_id: str, text: str, section: List[str]) -> None:
    chunk = {
        "doc_id": doc_id,
        "chunk_id": f"{doc_id}-c1",
        "order": 0,
        "rev": 1,
        "content": {"type": "text", "text": text},
        "source": {"page": 1, "section_path": section},
        "text_hash": "h",
        "metadata": {},
    }
    store.put_bytes(
        derived_key(doc_id, "chunks.jsonl"),
        (json.dumps(chunk) + "\n").encode("utf-8"),
    )


def test_csv_export_custom_template(test_app) -> None:
    client, store, _, SessionLocal = test_app
    _add_taxonomy(SessionLocal)
    _put_chunk(store, "d1", "alpha", ["A"])
    _put_chunk(store, "d2", "beta", ["B"])
    template = '{{ {"text": chunk.content.text, "page": chunk.source.page} | tojson }}'
    resp = client.post(
        "/export/csv",
        json={
            "project_id": str(PROJECT_ID_1),
            "doc_ids": ["d1", "d2"],
            "template": template,
        },
        headers={"X-Role": "curator"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "X-Amz-Expires" in data["url"]
    key = export_key(data["export_id"], "data.csv")
    lines = store.get_bytes(key).decode("utf-8").strip().splitlines()
    assert lines[0] == "page,text"
    assert lines[1:] == ["1,alpha", "1,beta"]
