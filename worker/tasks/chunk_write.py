from worker.celery_app import app
from worker.derived_writer import write_chunks
from worker.main import _get_store

from .utils import update_status


@app.task
def chunk_write(doc_id: str, request_id: str | None = None) -> str:
    update_status(doc_id, "chunk_write", request_id)
    store = _get_store()
    write_chunks(store, doc_id, [])
    return doc_id
