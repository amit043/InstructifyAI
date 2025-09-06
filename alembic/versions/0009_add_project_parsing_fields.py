"""add parsing/settings fields to projects"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0009"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "projects",
        sa.Column(
            "block_pii", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "ocr_langs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[\"eng\"]'::jsonb"),
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "min_text_len_for_ocr", sa.Integer(), nullable=False, server_default="50"
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "html_crawl_limits",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text('\'{"max_depth": 2, "max_pages": 50}\'::jsonb'),
        ),
    )


def downgrade():
    op.drop_column("projects", "html_crawl_limits")
    op.drop_column("projects", "min_text_len_for_ocr")
    op.drop_column("projects", "ocr_langs")
    op.drop_column("projects", "block_pii")
