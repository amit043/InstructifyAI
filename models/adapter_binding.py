from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base


class AdapterBinding(Base):
    __tablename__ = "adapter_bindings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=True
    )
    document_id: Mapped[str | None] = mapped_column(
        sa.String, sa.ForeignKey("documents.id"), nullable=True
    )
    backend: Mapped[str] = mapped_column(sa.String, nullable=False)
    base_model: Mapped[str] = mapped_column(sa.String, nullable=False)
    adapter_path: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    model_ref: Mapped[str] = mapped_column(sa.String, nullable=False)
    tag: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    priority: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=100, server_default=sa.text("100")
    )
    enabled: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        sa.CheckConstraint(
            "(project_id IS NOT NULL) OR (document_id IS NOT NULL)",
            name="ck_adapter_bindings_scope",
        ),
        sa.UniqueConstraint(
            "project_id", "document_id", "model_ref", "tag", name="uq_adapter_bindings_scope_ref"
        ),
        sa.Index("ix_adapter_bindings_document", "document_id", "priority", "created_at"),
        sa.Index("ix_adapter_bindings_project", "project_id", "priority", "created_at"),
    )


__all__ = ["AdapterBinding"]
