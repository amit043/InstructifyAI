import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .base import Base

json_dict = MutableDict.as_mutable(sa.JSON().with_variant(JSONB, "postgresql"))
json_list = MutableList.as_mutable(sa.JSON().with_variant(JSONB, "postgresql"))


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
    block_pii: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.text("false")
    )
    ocr_langs: Mapped[list[str]] = mapped_column(
        json_list,
        nullable=False,
        default=lambda: ["eng"],
        server_default=sa.text("'[\"eng\"]'"),
    )
    min_text_len_for_ocr: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=50,
        server_default=sa.text("50"),
    )
    html_crawl_limits: Mapped[dict[str, int]] = mapped_column(
        json_dict,
        nullable=False,
        default=lambda: {"max_depth": 2, "max_pages": 50},
        server_default=sa.text('\'{"max_depth":2,"max_pages":50}\''),
    )
    download_images: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.text("true")
    )
    max_image_bytes: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=2_000_000, server_default=sa.text("2000000")
    )
    chunk_token_target: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=1200, server_default=sa.text("1200")
    )
    chunk_token_overlap: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=200, server_default=sa.text("200")
    )
    deleted_at: Mapped[sa.types.DateTime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.text("true")
    )
    # Parser pipeline selector: "v1" (default) or "v2"
    parser_pipeline: Mapped[str] = mapped_column(
        sa.String,
        nullable=False,
        default="v1",
        server_default=sa.text("'v1'"),
    )
    created_at: Mapped[sa.types.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    documents = relationship("Document", back_populates="project")
