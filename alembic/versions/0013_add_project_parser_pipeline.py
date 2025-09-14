"""add parser_pipeline to projects

Revision ID: 0013
Revises: 0012
Create Date: 2025-08-30
"""

import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "parser_pipeline",
            sa.String(),
            nullable=False,
            server_default=sa.text("'v1'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "parser_pipeline")
