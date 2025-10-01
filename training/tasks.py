from __future__ import annotations

from typing import Any

from training.celery_app import app
from training.job_runner import execute_training_job


@app.task(name="training.run_training")
def run_training_task(run_id: str, config: dict[str, Any]) -> None:
    execute_training_job(run_id, config)
