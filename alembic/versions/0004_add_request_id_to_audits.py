"""add request_id to audits

Revision ID: 0004
Revises: 0003
Create Date: 2025-02-14
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audits", sa.Column("request_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("audits", "request_id")
