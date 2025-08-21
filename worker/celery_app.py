from __future__ import annotations

from celery import Celery  # type: ignore[import-untyped]

from core.settings import get_settings

settings = get_settings()

app = Celery("worker", broker=settings.redis_url)
app.conf.task_routes = {
    "worker.tasks.ocr.ocr_page": {"queue": "ocr"},
}
