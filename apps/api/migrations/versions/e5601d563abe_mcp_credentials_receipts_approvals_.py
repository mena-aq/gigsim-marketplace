"""mcp_credentials_receipts_approvals_workspace"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e5601d563abe"
down_revision = "1a5ff03eccdc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approval_grants",
        sa.Column("tool", sa.String(length=64), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_approval_grants_user_id"), "approval_grants", ["user_id"], unique=False
    )
    op.create_table(
        "email_drafts",
        sa.Column("recipient", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_email_drafts_user_id"), "email_drafts", ["user_id"], unique=False
    )
    op.create_table(
        "mcp_credentials",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("token_hash"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_table(
        "tool_receipts",
        sa.Column("tool", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "result",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "tool", "idempotency_key"),
    )
    op.create_index(
        op.f("ix_tool_receipts_user_id"), "tool_receipts", ["user_id"], unique=False
    )
    op.create_table(
        "workspace_holds",
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_workspace_holds_user_id"), "workspace_holds", ["user_id"], unique=False
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION reject_audit_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        RAISE EXCEPTION 'audit_log is append-only'; END $$""")
        op.execute("""CREATE TRIGGER audit_log_append_only
        BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW
        EXECUTE FUNCTION reject_audit_mutation()""")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER audit_log_append_only ON audit_log")
        op.execute("DROP FUNCTION reject_audit_mutation()")
    op.drop_index(op.f("ix_workspace_holds_user_id"), table_name="workspace_holds")
    op.drop_table("workspace_holds")
    op.drop_index(op.f("ix_tool_receipts_user_id"), table_name="tool_receipts")
    op.drop_table("tool_receipts")
    op.drop_table("mcp_credentials")
    op.drop_index(op.f("ix_email_drafts_user_id"), table_name="email_drafts")
    op.drop_table("email_drafts")
    op.drop_index(op.f("ix_approval_grants_user_id"), table_name="approval_grants")
    op.drop_table("approval_grants")
