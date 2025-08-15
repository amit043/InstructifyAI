from celery import Celery  # type: ignore[import-untyped]

from core.settings import get_settings

settings = get_settings()
app = Celery("worker", broker=settings.redis_url)


@app.task
def parse_document(doc_id: str) -> None:
    # Placeholder parse job
    return None


if __name__ == "__main__":
    app.worker_main()
