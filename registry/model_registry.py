from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.sql import func

from models.base import Base


class ModelRoute(Base):
    __tablename__ = "model_routes"

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), nullable=True
    )
    adapter_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sa.ForeignKey("adapters.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "project_id", "document_id", "adapter_id", name="uq_model_routes_key"
        ),
        sa.Index("ix_model_routes_project_document", "project_id", "document_id"),
    )


def _coerce_uuid(value: Optional[str]) -> Optional[uuid.UUID]:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(value)


def register_model_route(
    db: Session,
    *,
    project_id: str,
    adapter_id: str,
    document_id: Optional[str] = None,
) -> ModelRoute:
    """Register or refresh a model route for a project (and optional document)."""

    pid = _coerce_uuid(project_id)
    aid = _coerce_uuid(adapter_id)
    did = _coerce_uuid(document_id)
    assert pid is not None and aid is not None

    stmt = sa.select(ModelRoute).where(
        ModelRoute.project_id == pid,
        ModelRoute.adapter_id == aid,
    )
    if did is None:
        stmt = stmt.where(ModelRoute.document_id.is_(None))
    else:
        stmt = stmt.where(ModelRoute.document_id == did)
    existing = db.execute(stmt).scalar_one_or_none()
    if existing:
        existing.created_at = datetime.now(timezone.utc)
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    route = ModelRoute(project_id=pid, adapter_id=aid, document_id=did)
    db.add(route)
    db.commit()
    db.refresh(route)
    return route


def resolve_model_routes(
    db: Session,
    *,
    project_id: str,
    document_id: Optional[str] = None,
) -> list[ModelRoute]:
    """Return model routes for the document (if any) else project-level routes."""

    pid = _coerce_uuid(project_id)
    assert pid is not None

    if document_id:
        did = _coerce_uuid(document_id)
        if did is not None:
            doc_routes: Sequence[ModelRoute] = db.scalars(
                sa.select(ModelRoute)
                .where(
                    ModelRoute.project_id == pid,
                    ModelRoute.document_id == did,
                )
                .order_by(ModelRoute.created_at.desc())
            ).all()
            if doc_routes:
                return list(doc_routes)

    project_routes: Sequence[ModelRoute] = db.scalars(
        sa.select(ModelRoute)
        .where(ModelRoute.project_id == pid, ModelRoute.document_id.is_(None))
        .order_by(ModelRoute.created_at.desc())
    ).all()
    return list(project_routes)


__all__ = ["ModelRoute", "register_model_route", "resolve_model_routes"]
