import io
import json
import tarfile
import tempfile
from typing import List

import pytest

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


def test_parquet_export(test_app) -> None:
    pq = pytest.importorskip("pyarrow.parquet")
    client, store, _, SessionLocal = test_app
    _add_taxonomy(SessionLocal)
    _put_chunk(store, "d1", "hello", ["Intro"])
    _put_chunk(store, "d2", "world", ["Intro"])
    resp = client.post(
        "/export/parquet",
        json={
            "project_id": str(PROJECT_ID_1),
            "doc_ids": ["d1", "d2"],
            "preset": "rag",
        },
        headers={"X-Role": "curator"},
    )
    assert resp.status_code == 200
    data = resp.json()
    key = export_key(data["export_id"], "data.parquet")
    buf = io.BytesIO(store.get_bytes(key))
    table = pq.read_table(buf)
    assert table.column_names == ["answer", "context"]
    assert table.to_pylist() == [
        {"context": "Intro: hello", "answer": ""},
        {"context": "Intro: world", "answer": ""},
    ]


def test_hf_export(test_app) -> None:
    datasets = pytest.importorskip("datasets")
    DatasetDict = datasets.DatasetDict
    client, store, _, SessionLocal = test_app
    _add_taxonomy(SessionLocal)
    _put_chunk(store, "d1", "alpha", ["A"])
    _put_chunk(store, "d2", "beta", ["B"])
    resp = client.post(
        "/export/hf",
        json={
            "project_id": str(PROJECT_ID_1),
            "doc_ids": ["d1", "d2"],
            "preset": "sft",
        },
        headers={"X-Role": "curator"},
    )
    assert resp.status_code == 200
    data = resp.json()
    key = export_key(data["export_id"], "data.hf")
    buf = io.BytesIO(store.get_bytes(key))
    with tempfile.TemporaryDirectory() as tmp:
        tarfile.open(fileobj=buf, mode="r:gz").extractall(tmp)
        dsd = DatasetDict.load_from_disk(f"{tmp}/dataset")
        ds = dsd["train"]
        assert ds[0] == {"prompt": "alpha", "completion": ""}
        assert ds[1] == {"prompt": "beta", "completion": ""}
