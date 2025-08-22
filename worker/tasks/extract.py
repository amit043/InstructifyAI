from ops.metrics import timed_stage
from worker.celery_app import app

from .utils import update_status


@app.task
@timed_stage("extract")
def extract(doc_id: str, request_id: str | None = None) -> str:
    update_status(doc_id, "extract", request_id)
    return doc_id
