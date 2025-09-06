import json

import httpx

from storage.object_store import derived_key, raw_key
from tests.conftest import PROJECT_ID_1
from worker import main as worker_main


def _setup_worker(store, SessionLocal):
    worker_main.create_client = lambda **kwargs: store.client
    worker_main.settings.s3_bucket = store.bucket
    worker_main.SessionLocal = SessionLocal


def test_ingest_crawl(test_app) -> None:
    client, store, calls, SessionLocal = test_app
    crawl_calls: list[tuple[str, str, str | None, int, int, str | None, str | None]] = (
        []
    )
    worker_main.crawl_document.delay = lambda doc_id, base_url, allow_prefix, max_depth, max_pages, request_id=None, job_id=None: crawl_calls.append(
        (doc_id, base_url, allow_prefix, max_depth, max_pages, request_id, job_id)
    )

    resp = client.post(
        "/ingest/crawl",
        json={
            "project_id": str(PROJECT_ID_1),
            "base_url": "http://example.com/a",
            "allow_prefix": "/",
            "max_depth": 2,
            "max_pages": 5,
        },
    )
    assert resp.status_code == 200
    doc_id = resp.json()["doc_id"]
    assert crawl_calls and crawl_calls[0][0] == doc_id

    _setup_worker(store, SessionLocal)

    def mock_get(url, *args, **kwargs):
        class Resp:
            def __init__(self, text: str):
                self.status_code = 200
                self.text = text
                self.content = text.encode("utf-8")
                self.headers = {"content-type": "text/html"}

        if url == "http://example.com/a":
            return Resp(
                '<html><body><p>A</p><a href="/b">B</a><a href="/a">A</a></body></html>'
            )
        if url == "http://example.com/b":
            return Resp('<html><body><p>B</p><a href="/a">A</a></body></html>')
        return Resp("<html></html>")

    httpx.get = mock_get

    worker_main.parse_document.delay = lambda doc_id, version, parser_overrides=None, stages=None, reset_suggestions=False, job_id=None, request_id=None: worker_main.parse_document(
        doc_id, version
    )
    worker_main.crawl_document(doc_id, "http://example.com/a", "/", 2, 5)

    assert raw_key(doc_id, "crawl/page0.html") in store.client.store
    assert raw_key(doc_id, "crawl/page1.html") in store.client.store
    index = json.loads(store.client.store[raw_key(doc_id, "crawl/crawl_index.json")])
    assert len(index) == 2

    chunks_key = derived_key(doc_id, "chunks.jsonl")
    assert chunks_key in store.client.store
    lines = store.client.store[chunks_key].decode("utf-8").strip().splitlines()
    metas = [json.loads(line)["metadata"] for line in lines]
    urls = {m["url"] for m in metas}
    paths = {m["file_path"] for m in metas}
    assert {"http://example.com/a", "http://example.com/b"} <= urls
    assert {"page0.html", "page1.html"} <= paths
