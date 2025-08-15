import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base

json_type = sa.JSON().with_variant(JSONB, "postgresql")


class Taxonomy(Base):
    __tablename__ = "taxonomies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    fields: Mapped[list] = mapped_column("fields", json_type, nullable=False)
    created_at: Mapped[sa.types.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        sa.UniqueConstraint("project_id", "version", name="uq_taxonomy_proj_ver"),
    )
