import logging

from core.correlation import set_request_id
from tests.conftest import PROJECT_ID_1
from worker import main as worker_main


def test_request_id_propagates_to_celery(test_app) -> None:
    client, _, calls, _ = test_app
    resp = client.post(
        "/ingest",
        data={"project_id": str(PROJECT_ID_1)},
        files={"file": ("doc.txt", b"hello", "text/plain")},
        headers={"X-Request-ID": "rid-123"},
    )
    assert resp.status_code == 200
    doc_id = resp.json()["doc_id"]
    assert calls == [(doc_id, "rid-123")]


def test_worker_logs_include_request_id(caplog) -> None:
    set_request_id("rid-log")
    with caplog.at_level(logging.INFO):
        worker_main.logger.info("hello")
    assert any(record.request_id == "rid-log" for record in caplog.records)
