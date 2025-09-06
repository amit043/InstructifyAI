import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base

json_dict = MutableDict.as_mutable(sa.JSON().with_variant(JSONB, "postgresql"))


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(
        sa.String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    document_id: Mapped[str] = mapped_column(
        sa.String, sa.ForeignKey("documents.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    order: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    content: Mapped[dict] = mapped_column("content", json_dict, nullable=False)
    text_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    meta: Mapped[dict] = mapped_column(
        "metadata", json_dict, default=dict, nullable=False
    )
    rev: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    created_at: Mapped[sa.types.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "document_id", "version", "order", name="uq_chunk_doc_ver_order"
        ),
        sa.Index("ix_chunk_doc_order", "document_id", "order"),
    )
