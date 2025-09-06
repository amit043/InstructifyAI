import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base

json_dict = MutableDict.as_mutable(sa.JSON().with_variant(JSONB, "postgresql"))


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    filters: Mapped[dict] = mapped_column(json_dict, default=dict, nullable=False)
    snapshot_uri: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    stats: Mapped[dict] = mapped_column(json_dict, default=dict, nullable=False)
    created_at: Mapped[sa.types.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[sa.types.DateTime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (sa.Index("ix_datasets_project_id", "project_id"),)
