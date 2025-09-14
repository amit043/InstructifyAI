import io
import json
from zipfile import ZipFile

from storage.object_store import derived_key, raw_key
from tests.conftest import PROJECT_ID_1


def test_ingest_html_zip_multipart(test_app) -> None:
    client, store, _calls, _ = test_app

    # Build a small zip with two HTML files
    buf = io.BytesIO()
    with ZipFile(buf, "w") as zf:
        zf.writestr("a.html", "<html><body><h1>A</h1><p>One</p></body></html>")
        zf.writestr("sub/b.html", "<html><body><h2>B</h2><p>Two</p></body></html>")
    buf.seek(0)

    resp = client.post(
        "/ingest/html",
        data={"project_id": str(PROJECT_ID_1)},
        files={"file": ("bundle.zip", buf.read(), "application/zip")},
        headers={"X-Role": "viewer"},
    )
    assert resp.status_code == 200
    doc_id = resp.json()["doc_id"]

    chunks_key = derived_key(doc_id, "chunks.jsonl")
    assert chunks_key in store.client.store
    lines = store.client.store[chunks_key].decode("utf-8").strip().splitlines()
    metas = [json.loads(line)["metadata"] for line in lines]
    paths = {m.get("file_path") for m in metas}
    assert {"a.html", "sub/b.html"} <= paths


def test_ingest_html_single_url_json(test_app, monkeypatch) -> None:
    client, store, _calls, _ = test_app

    class Resp:
        def __init__(self, data: bytes):
            self.data = data

        def read(self):  # urllib style
            return self.data

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        @property
        def headers(self):
            class H:
                def get_content_type(self):
                    return "text/html"

            return H()

    def fake_urlopen(url):  # noqa: ANN001
        html = b"<html><body><h1>T</h1><p>Hello</p></body></html>"
        return Resp(html)

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    resp = client.post(
        "/ingest/html",
        json={"project_id": str(PROJECT_ID_1), "uri": "http://example.com/index.html"},
        headers={"X-Role": "viewer"},
    )
    assert resp.status_code == 200
    doc_id = resp.json()["doc_id"]
    # Raw index stored
    assert raw_key(doc_id, "index.html") in store.client.store
    # Derived chunks exist
    chunks_key = derived_key(doc_id, "chunks.jsonl")
    assert chunks_key in store.client.store


def test_ingest_html_crawl_json(test_app, monkeypatch) -> None:
    client, store, _calls, _ = test_app

    # Mock httpx.get to return a small two-page site
    import httpx

    def mock_get(url, *args, **kwargs):  # noqa: ANN001, D401
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

    monkeypatch.setattr(httpx, "get", mock_get)

    resp = client.post(
        "/ingest/html",
        json={
            "project_id": str(PROJECT_ID_1),
            "uri": "http://example.com/a",
            "crawl": True,
            "max_depth": 2,
            "max_pages": 5,
        },
        headers={"X-Role": "viewer"},
    )
    assert resp.status_code == 200
    doc_id = resp.json()["doc_id"]
    chunks_key = derived_key(doc_id, "chunks.jsonl")
    assert chunks_key in store.client.store
    lines = store.client.store[chunks_key].decode("utf-8").strip().splitlines()
    metas = [json.loads(line)["metadata"] for line in lines]
    urls = {m.get("url") for m in metas}
    paths = {m.get("file_path") for m in metas}
    assert {"http://example.com/a", "http://example.com/b"} <= urls
    assert {"page0.html", "page1.html"} <= paths

