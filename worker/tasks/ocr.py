from worker.celery_app import app

from .utils import update_status


@app.task
def ocr_page(doc_id: str, page_hash: str, request_id: str | None = None) -> str:
    update_status(doc_id, f"ocr:{page_hash}", request_id)
    return doc_id
