from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship, Session
from sqlalchemy.sql import func

from models.base import Base


json_dict = MutableDict.as_mutable(sa.JSON().with_variant(JSONB, "postgresql"))


class PeftType(enum.Enum):
    dora = "dora"
    lora = "lora"
    qlora = "qlora"
    rwkv_state = "rwkv_state"


class TrainMode(enum.Enum):
    sft = "sft"
    mft = "mft"
    orpo = "orpo"


class Adapter(Base):
    __tablename__ = "adapters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    base_model: Mapped[str] = mapped_column(sa.String, nullable=False)
    peft_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    task_types: Mapped[dict[str, Any]] = mapped_column(json_dict, nullable=False, default=dict)
    artifact_uri: Mapped[str] = mapped_column(sa.String, nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False, server_default=sa.text("false"))
    metrics: Mapped[dict[str, Any] | None] = mapped_column(json_dict, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=func.now(), nullable=False)


class TrainingRun(Base):
    __tablename__ = "training_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False)
    mode: Mapped[str] = mapped_column(sa.String, nullable=False)
    base_model: Mapped[str] = mapped_column(sa.String, nullable=False)
    peft_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    input_uri: Mapped[str] = mapped_column(sa.String, nullable=False)
    output_uri: Mapped[str] = mapped_column(sa.String, nullable=False)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(json_dict, nullable=True)
    status: Mapped[str] = mapped_column(sa.String, nullable=False, default="completed", server_default=sa.text("'completed'"))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=func.now(), nullable=False)


def register_adapter(
    db: Session,
    *,
    project_id: str,
    name: str,
    base_model: str,
    peft_type: str,
    task_types: dict[str, Any],
    artifact_uri: str,
    metrics: Optional[dict[str, Any]] = None,
    activate: bool = True,
) -> Adapter:
    """Register an adapter and optionally activate it for the project."""
    ad = Adapter(
        project_id=uuid.UUID(project_id),
        name=name,
        base_model=base_model,
        peft_type=peft_type,
        task_types=task_types,
        artifact_uri=artifact_uri,
        metrics=metrics,
        is_active=False,
    )
    db.add(ad)
    db.commit()
    db.refresh(ad)
    if activate:
        activate_adapter(db, project_id=project_id, adapter_id=str(ad.id))
        db.refresh(ad)
    return ad


def activate_adapter(db: Session, *, project_id: str, adapter_id: str) -> None:
    pid = uuid.UUID(project_id)
    aid = uuid.UUID(adapter_id)
    db.execute(sa.update(Adapter).where(Adapter.project_id == pid).values(is_active=False))
    db.execute(sa.update(Adapter).where(Adapter.id == aid).values(is_active=True))
    db.commit()


def get_active_adapter(db: Session, project_id: str) -> Adapter | None:
    pid = uuid.UUID(project_id)
    row = db.execute(sa.select(Adapter).where(Adapter.project_id == pid, Adapter.is_active == True)).scalar_one_or_none()  # noqa: E712
    return row


__all__ = ["Adapter", "TrainingRun", "register_adapter", "activate_adapter", "get_active_adapter"]

