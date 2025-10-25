"""revert doc_id columns back to document_id naming"""

from __future__ import annotations

from alembic import op


revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # training_runs doc_id -> document_id
    op.alter_column("training_runs", "doc_id", new_column_name="document_id")

    # model_routes doc_id -> document_id (drop/recreate constraints to update column list)
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

    # adapter_bindings doc_id -> document_id
    op.drop_index("ix_adapter_bindings_doc", table_name="adapter_bindings")
    op.drop_constraint("uq_adapter_bindings_scope_ref", "adapter_bindings", type_="unique")
    op.alter_column("adapter_bindings", "doc_id", new_column_name="document_id")
    op.create_unique_constraint(
        "uq_adapter_bindings_scope_ref",
        "adapter_bindings",
        ["project_id", "document_id", "model_ref", "tag"],
    )
    op.create_index(
        "ix_adapter_bindings_document",
        "adapter_bindings",
        ["document_id", "priority", "created_at"],
    )


def downgrade() -> None:
    # adapter_bindings document_id -> doc_id
    op.drop_index("ix_adapter_bindings_document", table_name="adapter_bindings")
    op.drop_constraint("uq_adapter_bindings_scope_ref", "adapter_bindings", type_="unique")
    op.alter_column("adapter_bindings", "document_id", new_column_name="doc_id")
    op.create_unique_constraint(
        "uq_adapter_bindings_scope_ref",
        "adapter_bindings",
        ["project_id", "doc_id", "model_ref", "tag"],
    )
    op.create_index(
        "ix_adapter_bindings_doc",
        "adapter_bindings",
        ["doc_id", "priority", "created_at"],
    )

    # model_routes document_id -> doc_id
    op.drop_index("ix_model_routes_project_document", table_name="model_routes")
    op.drop_constraint("uq_model_routes_key", "model_routes", type_="unique")
    op.alter_column("model_routes", "document_id", new_column_name="doc_id")
    op.create_unique_constraint(
        "uq_model_routes_key", "model_routes", ["project_id", "doc_id", "adapter_id"]
    )
    op.create_index(
        "ix_model_routes_project_doc",
        "model_routes",
        ["project_id", "doc_id"],
    )

    # training_runs document_id -> doc_id
    op.alter_column("training_runs", "document_id", new_column_name="doc_id")
