"""rename document columns to doc_id

Revision ID: 0019_rename_document_columns
Revises: 0018_add_model_routes
Create Date: 2025-10-03 14:35:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("training_runs", "document_id", new_column_name="doc_id")
    op.drop_constraint("uq_model_routes_key", "model_routes", type_="unique")
    op.drop_index("ix_model_routes_project_document", table_name="model_routes")
    op.alter_column("model_routes", "document_id", new_column_name="doc_id")
    op.create_unique_constraint(
        "uq_model_routes_key", "model_routes", ["project_id", "doc_id", "adapter_id"]
    )
    op.create_index(
        "ix_model_routes_project_doc",
        "model_routes",
        ["project_id", "doc_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_model_routes_project_doc", table_name="model_routes")
    op.drop_constraint("uq_model_routes_key", "model_routes", type_="unique")
    op.alter_column("model_routes", "doc_id", new_column_name="document_id")
    op.create_unique_constraint(
        "uq_model_routes_key", "model_routes", ["project_id", "document_id", "adapter_id"]
    )
    op.create_index(
        "ix_model_routes_project_document",
        "model_routes",
        ["project_id", "document_id"],
    )
    op.alter_column("training_runs", "doc_id", new_column_name="document_id")
