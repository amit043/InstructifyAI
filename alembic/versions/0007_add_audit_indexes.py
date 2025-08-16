import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_audits_chunk_id_created_at",
        "audits",
        ["chunk_id", "created_at"],
    )
    op.create_index("ix_audits_action", "audits", ["action"])


def downgrade() -> None:
    op.drop_index("ix_audits_action", table_name="audits")
    op.drop_index("ix_audits_chunk_id_created_at", table_name="audits")
