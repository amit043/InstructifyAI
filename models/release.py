import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base

json_type = sa.JSON().with_variant(JSONB, "postgresql")


class Release(Base):
    """Immutable dataset release snapshot."""

    __tablename__ = "releases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False
    )
    manifest: Mapped[dict] = mapped_column("manifest", json_type, nullable=False)
    content_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    created_at: Mapped[sa.types.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )
