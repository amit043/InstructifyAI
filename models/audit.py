import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base

json_type = sa.JSON().with_variant(JSONB, "postgresql")


class Audit(Base):
    __tablename__ = "audits"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    chunk_id: Mapped[str] = mapped_column(
        sa.String, sa.ForeignKey("chunks.id"), nullable=False
    )
    user: Mapped[str] = mapped_column(sa.String, nullable=False)
    action: Mapped[str] = mapped_column(sa.String, nullable=False)
    before: Mapped[dict] = mapped_column("before", json_type, nullable=False)
    after: Mapped[dict] = mapped_column("after", json_type, nullable=False)
    created_at: Mapped[sa.types.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )
