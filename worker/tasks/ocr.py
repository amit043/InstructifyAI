from worker.main import app

from .utils import update_status


@app.task
def ocr_page(doc_id: str, request_id: str | None = None) -> str:
    update_status(doc_id, "ocr", request_id)
    return doc_id
