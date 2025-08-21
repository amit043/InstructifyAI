from models import DocumentStatus
from worker.celery_app import app

from .utils import update_status


@app.task
def finalize(doc_id: str, request_id: str | None = None) -> str:
    update_status(doc_id, DocumentStatus.PARSED.value, request_id, action="finalize")
    return doc_id
