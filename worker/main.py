from celery import Celery  # type: ignore[import-untyped]

from core.settings import get_settings

settings = get_settings()
app = Celery("worker", broker=settings.redis_url)


@app.task
def noop() -> None:
    return None


if __name__ == "__main__":
    app.worker_main()
