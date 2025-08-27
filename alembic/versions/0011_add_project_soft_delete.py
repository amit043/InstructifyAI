"""add soft delete to projects"""

import sqlalchemy as sa

from alembic import op

revision = "0011_add_project_soft_delete"
down_revision = "0010_add_jobs_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "is_active")
    op.drop_column("projects", "deleted_at")
