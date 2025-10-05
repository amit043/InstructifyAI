"""add model routes table and training run document id"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0018_add_model_routes"
down_revision = "0017_add_ls_project_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "training_runs",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.create_table(
        "model_routes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("adapter_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("adapters.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "document_id", "adapter_id", name="uq_model_routes_key"),
    )
    op.create_index(
        "ix_model_routes_project_document",
        "model_routes",
        ["project_id", "document_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_model_routes_project_document", table_name="model_routes")
    op.drop_table("model_routes")
    op.drop_column("training_runs", "document_id")
