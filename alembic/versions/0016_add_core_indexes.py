"""add core indexes for performance

Revision ID: 0016_add_core_indexes
Revises: 0015_add_adapters_training_runs
Create Date: 2025-09-07
"""

from alembic import op


revision = "0016_add_core_indexes"
down_revision = "0015_add_adapters_training_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Non-unique btree for common chunk queries; note a unique constraint on
    # (document_id, version, "order") already exists and provides an index in
    # most environments. Using IF NOT EXISTS ensures we don't duplicate.
    op.execute(
        'CREATE INDEX IF NOT EXISTS ix_chunks_doc_ver_order ON chunks USING btree (document_id, version, "order")'
    )

    # Speed project-scoped document listings
    op.execute(
        'CREATE INDEX IF NOT EXISTS ix_documents_project_id ON documents USING btree (project_id)'
    )

    # Enable fast JSONB containment queries over chunk metadata
    op.execute(
        'CREATE INDEX IF NOT EXISTS ix_chunks_metadata_gin ON chunks USING gin ("metadata")'
    )


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS ix_chunks_metadata_gin')
    op.execute('DROP INDEX IF EXISTS ix_documents_project_id')
    op.execute('DROP INDEX IF EXISTS ix_chunks_doc_ver_order')
