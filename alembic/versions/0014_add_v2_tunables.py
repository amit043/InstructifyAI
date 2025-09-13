"""add v2 tunables to projects

Revision ID: 0014
Revises: 0013
Create Date: 2025-08-30
"""

import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "download_images",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "max_image_bytes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("2000000"),
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "chunk_token_target",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1200"),
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "chunk_token_overlap",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("200"),
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "chunk_token_overlap")
    op.drop_column("projects", "chunk_token_target")
    op.drop_column("projects", "max_image_bytes")
    op.drop_column("projects", "download_images")
