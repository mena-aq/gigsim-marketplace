"""Make stored recommendation fields required."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "c7400_persona_job_required"
down_revision = "c7300_persona_job_matches"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "persona_job_matches",
        "matched_skills",
        existing_type=sa.JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )
    op.alter_column(
        "persona_job_matches",
        "job",
        existing_type=sa.JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )


def downgrade():
    op.alter_column(
        "persona_job_matches",
        "matched_skills",
        existing_type=sa.JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
    )
    op.alter_column(
        "persona_job_matches",
        "job",
        existing_type=sa.JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
    )
