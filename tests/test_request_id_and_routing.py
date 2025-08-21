from worker import flow
from worker.celery_app import app


def test_request_id_and_ocr_queue() -> None:
    sig = flow.build_flow("doc1", request_id="rid", do_ocr=True)
    tasks = sig.tasks

    for idx in [0, 1, 2, 4, 5]:
        assert tasks[idx].kwargs["request_id"] == "rid"

    ocr_chord = tasks[3]
    assert ocr_chord.body.kwargs["request_id"] == "rid"
    for t in ocr_chord.tasks:
        assert t.kwargs["request_id"] == "rid"
        assert t.options.get("queue") == "ocr"

    assert app.conf.task_routes["worker.tasks.ocr.ocr_page"]["queue"] == "ocr"
