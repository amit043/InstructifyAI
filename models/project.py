import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .base import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    slug: Mapped[str] = mapped_column(sa.String, nullable=False, unique=True)
    allow_versioning: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False
    )
    use_rules_suggestor: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.text("true")
    )
    use_mini_llm: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.text("false")
    )
    max_suggestions_per_doc: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=200, server_default=sa.text("200")
    )
    suggestion_timeout_ms: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=500, server_default=sa.text("500")
    )
    ocr_langs: Mapped[list[str]] = mapped_column(sa.JSON, nullable=False, default=list)
    min_text_len_for_ocr: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0
    )
    html_crawl_limits: Mapped[dict[str, int]] = mapped_column(
        sa.JSON, nullable=False, default=dict
    )
    created_at: Mapped[sa.types.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    documents = relationship("Document", back_populates="project")
