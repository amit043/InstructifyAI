from models import Document
from tests.conftest import PROJECT_ID_1


def test_reparse_in_place(test_app) -> None:
    client, _, calls, SessionLocal = test_app
    data = b"<html><body>hello</body></html>"
    resp = client.post(
        "/ingest",
        data={"project_id": str(PROJECT_ID_1)},
        files={"file": ("a.html", data, "text/html")},
    )
    doc_id = resp.json()["doc_id"]
    calls.clear()
    resp2 = client.post(f"/documents/{doc_id}/reparse")
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["version"] == 1
    assert calls and calls[0][0] == doc_id and calls[0][1] == 1


def test_reparse_version_bump(test_app) -> None:
    client, _, calls, SessionLocal = test_app
    data = b"<html><body>hello</body></html>"
    resp = client.post(
        "/ingest",
        data={"project_id": str(PROJECT_ID_1)},
        files={"file": ("a.html", data, "text/html")},
    )
    doc_id = resp.json()["doc_id"]
    calls.clear()
    resp2 = client.post(
        f"/documents/{doc_id}/reparse", params={"force_version_bump": "true"}
    )
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["version"] == 2
    assert calls and calls[0][0] == doc_id and calls[0][1] == 2
    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        assert doc is not None and doc.latest_version.version == 2
