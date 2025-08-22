from ops.metrics import timed_stage
from worker.celery_app import app

from .utils import update_status


@app.task
@timed_stage("structure")
def structure(doc_id: str | list[str], request_id: str | None = None) -> str:
    if isinstance(doc_id, list):
        doc_id = doc_id[0]
    update_status(doc_id, "structure", request_id)
    return doc_id
