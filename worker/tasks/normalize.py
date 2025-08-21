from worker.celery_app import app

from .utils import update_status


@app.task
def normalize(doc_id: str, request_id: str | None = None) -> str:
    update_status(doc_id, "normalize", request_id)
    return doc_id
