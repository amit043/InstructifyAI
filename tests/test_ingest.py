from tests.conftest import PROJECT_ID_1


def test_deduplication(test_app) -> None:
    client, store, calls, _ = test_app
    resp = client.post(
        "/ingest",
        data={"project_id": str(PROJECT_ID_1)},
        files={"file": ("doc.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 200
    doc_id = resp.json()["doc_id"]
    assert calls == [doc_id]
    assert len(store.client.store) == 1

    resp2 = client.post(
        "/ingest",
        data={"project_id": str(PROJECT_ID_1)},
        files={"file": ("doc.txt", b"hello", "text/plain")},
    )
    assert resp2.status_code == 200
    assert resp2.json()["doc_id"] == doc_id
    assert len(store.client.store) == 1
    assert calls == [doc_id]
