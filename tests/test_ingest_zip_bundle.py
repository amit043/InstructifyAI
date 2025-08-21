import json
from io import BytesIO
from zipfile import ZipFile

from storage.object_store import derived_key, raw_bundle_key
from tests.conftest import PROJECT_ID_1
from worker import main as worker_main


def _setup_worker(store, SessionLocal):
    worker_main.create_client = lambda **kwargs: store.client
    worker_main.settings.s3_bucket = store.bucket
    worker_main.SessionLocal = SessionLocal


def test_ingest_zip_bundle(test_app) -> None:
    client, store, calls, SessionLocal = test_app
    buf = BytesIO()
    with ZipFile(buf, "w") as zf:
        zf.writestr("a.html", "<html><body><p>A</p></body></html>")
        zf.writestr("b/b.html", "<html><body><p>B</p></body></html>")
    data = buf.getvalue()
    resp = client.post(
        "/ingest/zip",
        data={"project_id": str(PROJECT_ID_1)},
        files={"file": ("bundle.zip", data, "application/zip")},
    )
    assert resp.status_code == 200
    doc_id = resp.json()["doc_id"]
    assert raw_bundle_key(doc_id) in store.client.store
    assert [c[0] for c in calls] == [doc_id]

    _setup_worker(store, SessionLocal)
    worker_main.parse_document(doc_id)

    chunks_key = derived_key(doc_id, "chunks.jsonl")
    manifest_key = derived_key(doc_id, "manifest.json")
    assert chunks_key in store.client.store
    assert manifest_key in store.client.store

    lines = store.client.store[chunks_key].decode("utf-8").strip().splitlines()
    paths = {json.loads(line)["metadata"].get("file_path") for line in lines}
    assert {"a.html", "b/b.html"} <= paths

    manifest = json.loads(store.client.store[manifest_key])
    assert sorted(manifest["files"]) == ["a.html", "b/b.html"]
