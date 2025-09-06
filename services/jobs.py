import uuid
from typing import Any

from sqlalchemy.orm import Session

from models import Job, JobState, JobType


def create_job(
    db: Session,
    job_type: JobType | str,
    project_id: uuid.UUID,
    doc_id: uuid.UUID | None = None,
    celery_task_id: str | None = None,
) -> Job:
    job = Job(
        type=JobType(job_type),
        project_id=project_id,
        doc_id=doc_id,
        celery_task_id=celery_task_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def set_progress(
    db: Session,
    job_id: uuid.UUID,
    progress: int,
    artifacts: dict[str, Any] | None = None,
) -> Job | None:
    job = db.get(Job, job_id)
    if job is None:
        return None
    job.state = JobState.RUNNING
    job.progress = progress
    if artifacts:
        data = dict(job.artifacts or {})
        data.update(artifacts)
        job.artifacts = data
    db.commit()
    db.refresh(job)
    return job


def set_done(
    db: Session,
    job_id: uuid.UUID,
    artifacts: dict[str, Any] | None = None,
) -> Job | None:
    job = db.get(Job, job_id)
    if job is None:
        return None
    job.state = JobState.SUCCEEDED
    job.progress = 100
    if artifacts:
        data = dict(job.artifacts or {})
        data.update(artifacts)
        job.artifacts = data
    db.commit()
    db.refresh(job)
    return job


def set_failed(
    db: Session,
    job_id: uuid.UUID,
    error: str,
    artifacts: dict[str, Any] | None = None,
) -> Job | None:
    job = db.get(Job, job_id)
    if job is None:
        return None
    job.state = JobState.FAILED
    job.error = error
    if artifacts:
        data = dict(job.artifacts or {})
        data.update(artifacts)
        job.artifacts = data
    db.commit()
    db.refresh(job)
    return job
