"""add adapters and training runs tables

Revision ID: 0015_add_adapters_training_runs
Revises: 0014_add_v2_tunables
Create Date: 2025-09-06 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0015_add_adapters_training_runs"
down_revision = "0014_add_v2_tunables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "adapters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("base_model", sa.String(), nullable=False),
        sa.Column("peft_type", sa.String(), nullable=False),
        sa.Column("task_types", sa.JSON().with_variant(postgresql.JSONB, "postgresql"), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("artifact_uri", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("metrics", sa.JSON().with_variant(postgresql.JSONB, "postgresql"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "training_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("base_model", sa.String(), nullable=False),
        sa.Column("peft_type", sa.String(), nullable=False),
        sa.Column("input_uri", sa.String(), nullable=False),
        sa.Column("output_uri", sa.String(), nullable=False),
        sa.Column("metrics", sa.JSON().with_variant(postgresql.JSONB, "postgresql"), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'completed'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("training_runs")
    op.drop_table("adapters")

