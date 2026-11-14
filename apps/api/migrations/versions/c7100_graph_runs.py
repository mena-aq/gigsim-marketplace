"""Durable orchestration outbox; LangGraph owns its checkpoint/store tables."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "c7100_graph_runs"
down_revision = "e5601d563abe"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "graph_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("target", sa.String(160), nullable=False),
        sa.Column("turn", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("trace_id", sa.String(128), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
        sa.Column("resume", sa.JSON().with_variant(JSONB(), "postgresql")),
        sa.Column("error", sa.JSON().with_variant(JSONB(), "postgresql")),
        sa.UniqueConstraint("user_id", "kind", "target", "turn"),
    )
    op.create_index("ix_graph_runs_user_id", "graph_runs", ["user_id"])
    op.create_index("ix_graph_runs_status", "graph_runs", ["status"])


def downgrade():
    op.drop_table("graph_runs")
