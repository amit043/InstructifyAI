import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


job_state = sa.Enum("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", name="job_state")

job_type = sa.Enum(
    "INGEST",
    "PARSE",
    "REPARSE",
    "DATASET",
    "EXPORT",
    "QA_GENERATE",
    name="job_type",
)


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("type", job_type, nullable=False),
        sa.Column(
            "project_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("doc_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("state", job_state, nullable=False),
        sa.Column(
            "progress",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("celery_task_id", sa.Text(), nullable=True),
        sa.Column(
            "artifacts",
            sa.JSON().with_variant(postgresql.JSONB, "postgresql"),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "progress >= 0 AND progress <= 100", name="ck_jobs_progress"
        ),
    )
    op.create_index(
        "ix_jobs_project_state_type",
        "jobs",
        ["project_id", "state", "type"],
    )
    op.create_index("ix_jobs_doc_id", "jobs", ["doc_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_doc_id", table_name="jobs")
    op.drop_index("ix_jobs_project_state_type", table_name="jobs")
    op.drop_table("jobs")
    job_state.drop(op.get_bind(), checkfirst=False)
    job_type.drop(op.get_bind(), checkfirst=False)
