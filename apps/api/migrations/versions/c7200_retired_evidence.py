"""Per-user retired evidence so deleted portfolio items never support claims."""

import sqlalchemy as sa
from alembic import op

revision = "c7200_retired_evidence"
down_revision = "c7100_graph_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "retired_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("item_id", sa.String(250), nullable=False),
        sa.UniqueConstraint("user_id", "item_id"),
    )
    op.create_index("ix_retired_evidence_user_id", "retired_evidence", ["user_id"])


def downgrade():
    op.drop_table("retired_evidence")
