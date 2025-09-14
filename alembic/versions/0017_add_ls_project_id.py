"""add ls_project_id to projects

Revision ID: 0017_add_ls_project_id
Revises: 0016_add_core_indexes
Create Date: 2025-09-07
"""

from alembic import op
import sqlalchemy as sa


revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("ls_project_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "ls_project_id")

