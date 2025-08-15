from celery import Celery  # type: ignore[import-untyped]

from core.correlation import set_request_id
from core.settings import get_settings

settings = get_settings()
app = Celery("worker", broker=settings.redis_url)


@app.task
def parse_document(doc_id: str, request_id: str | None = None) -> None:
    """Placeholder parse job that receives a correlation id."""
    set_request_id(request_id)
    return None


if __name__ == "__main__":
    app.worker_main()
