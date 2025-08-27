import enum
import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .base import Base


class DocumentStatus(str, enum.Enum):
    INGESTED = "ingested"
    PARSING = "parsing"
    PARSED = "parsed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


json_dict = MutableDict.as_mutable(sa.JSON().with_variant(JSONB, "postgresql"))


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(
        sa.String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    created_at: Mapped[sa.types.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    latest_version_id: Mapped[str | None] = mapped_column(
        sa.String, sa.ForeignKey("document_versions.id"), nullable=True
    )

    project = relationship("Project", back_populates="documents")
    versions = relationship(
        "DocumentVersion",
        back_populates="document",
        foreign_keys="DocumentVersion.document_id",
    )
    latest_version = relationship(
        "DocumentVersion", foreign_keys=[latest_version_id], uselist=False
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id: Mapped[str] = mapped_column(
        sa.String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    document_id: Mapped[str] = mapped_column(
        sa.String, sa.ForeignKey("documents.id"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    doc_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    mime: Mapped[str] = mapped_column(sa.String, nullable=False)
    size: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    status: Mapped[str] = mapped_column(sa.String, nullable=False)
    meta: Mapped[dict] = mapped_column(
        "metadata", json_dict, default=dict, nullable=False
    )
    created_at: Mapped[sa.types.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document = relationship(
        "Document",
        back_populates="versions",
        foreign_keys=[document_id],
    )

    __table_args__ = (
        sa.UniqueConstraint("document_id", "version", name="uq_document_version"),
        sa.UniqueConstraint("project_id", "doc_hash", name="uq_project_doc_hash"),
    )
