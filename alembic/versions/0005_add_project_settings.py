"""add project settings

Revision ID: 0005
Revises: 0004
Create Date: 2025-08-15
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "use_rules_suggestor",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "use_mini_llm",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "max_suggestions_per_doc",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("200"),
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "suggestion_timeout_ms",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("500"),
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "suggestion_timeout_ms")
    op.drop_column("projects", "max_suggestions_per_doc")
    op.drop_column("projects", "use_mini_llm")
    op.drop_column("projects", "use_rules_suggestor")
