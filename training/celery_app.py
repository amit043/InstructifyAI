from __future__ import annotations

from celery import Celery  # type: ignore[import-untyped]

from core.settings import get_settings

settings = get_settings()

app = Celery("trainer", broker=settings.redis_url)
app.conf.task_default_queue = "training"
app.autodiscover_tasks(["training"])
