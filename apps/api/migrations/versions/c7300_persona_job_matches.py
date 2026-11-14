"""Stored per-persona job recommendations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "c7300_persona_job_matches"
down_revision = "c7200_retired_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "persona_job_matches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("persona", sa.String(64), nullable=False),
        sa.Column("job_id", sa.String(64), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("matched_skills", sa.JSON().with_variant(JSONB(), "postgresql")),
        sa.Column("job", sa.JSON().with_variant(JSONB(), "postgresql")),
        sa.UniqueConstraint("persona", "job_id"),
    )
    op.create_index(
        "ix_persona_job_matches_persona", "persona_job_matches", ["persona"]
    )


def downgrade():
    op.drop_table("persona_job_matches")
