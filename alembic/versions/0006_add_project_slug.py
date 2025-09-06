import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(sa.Column("slug", sa.String(), nullable=False))
        batch_op.create_unique_constraint("uq_projects_slug", ["slug"])


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_constraint("uq_projects_slug", type_="unique")
        batch_op.drop_column("slug")
