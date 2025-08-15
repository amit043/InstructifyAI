import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "taxonomies",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "fields",
            sa.JSON().with_variant(postgresql.JSONB, "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("project_id", "version", name="uq_taxonomy_proj_ver"),
    )

    op.create_table(
        "audits",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "chunk_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("chunks.id"),
            nullable=False,
        ),
        sa.Column("user", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column(
            "before",
            sa.JSON().with_variant(postgresql.JSONB, "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "after",
            sa.JSON().with_variant(postgresql.JSONB, "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("audits")
    op.drop_table("taxonomies")
