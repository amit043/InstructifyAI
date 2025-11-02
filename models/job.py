import enum
import uuid
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base


class JobType(str, enum.Enum):
    INGEST = "ingest"
    PARSE = "parse"
    REPARSE = "reparse"
    DATASET = "dataset"
    EXPORT = "export"
    QA_GENERATE = "qa_generate"


class JobState(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


json_dict = MutableDict.as_mutable(sa.JSON().with_variant(JSONB, "postgresql"))


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    type: Mapped[JobType] = mapped_column(
        sa.Enum(JobType, name="job_type"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False
    )
    doc_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    state: Mapped[JobState] = mapped_column(
        sa.Enum(JobState, name="job_state"),
        nullable=False,
        default=JobState.QUEUED,
    )
    progress: Mapped[int] = mapped_column(
        sa.Integer,
        sa.CheckConstraint("progress >= 0 AND progress <= 100"),
        nullable=False,
        default=0,
    )
    celery_task_id: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    artifacts: Mapped[dict] = mapped_column(json_dict, default=dict, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[sa.types.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[sa.types.DateTime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        sa.Index("ix_jobs_project_state_type", "project_id", "state", "type"),
        sa.Index("ix_jobs_doc_id", "doc_id"),
    )
