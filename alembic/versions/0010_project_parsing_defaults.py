"""add project parsing fields with defaults"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0010"
down_revision = "add_project_parsing_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE projects
        ADD COLUMN IF NOT EXISTS block_pii BOOLEAN NOT NULL DEFAULT false
        """
    )
    op.execute(
        """
        ALTER TABLE projects
        ADD COLUMN IF NOT EXISTS ocr_langs JSONB NOT NULL DEFAULT '["eng"]'::jsonb
        """
    )
    op.execute(
        """
        ALTER TABLE projects
        ADD COLUMN IF NOT EXISTS min_text_len_for_ocr INTEGER NOT NULL DEFAULT 50
        """
    )
    op.execute(
        """
        ALTER TABLE projects
        ADD COLUMN IF NOT EXISTS html_crawl_limits JSONB NOT NULL DEFAULT '{"max_depth":2,"max_pages":50}'::jsonb
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS html_crawl_limits")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS min_text_len_for_ocr")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS ocr_langs")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS block_pii")
