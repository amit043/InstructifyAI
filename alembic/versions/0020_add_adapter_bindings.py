"""add adapter bindings table"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "adapter_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("doc_id", sa.String(), sa.ForeignKey("documents.id"), nullable=True),
        sa.Column("backend", sa.String(), nullable=False),
        sa.Column("base_model", sa.String(), nullable=False),
        sa.Column("adapter_path", sa.String(), nullable=True),
        sa.Column("model_ref", sa.String(), nullable=False),
        sa.Column("tag", sa.String(), nullable=True),
        sa.Column("priority", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "(project_id IS NOT NULL) OR (doc_id IS NOT NULL)",
            name="ck_adapter_bindings_scope",
        ),
        sa.UniqueConstraint(
            "project_id", "doc_id", "model_ref", "tag", name="uq_adapter_bindings_scope_ref"
        ),
    )
    op.create_index(
        "ix_adapter_bindings_doc", "adapter_bindings", ["doc_id", "priority", "created_at"]
    )
    op.create_index(
        "ix_adapter_bindings_project",
        "adapter_bindings",
        ["project_id", "priority", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_adapter_bindings_project", table_name="adapter_bindings")
    op.drop_index("ix_adapter_bindings_doc", table_name="adapter_bindings")
    op.drop_table("adapter_bindings")
