"""idempotency keys table

Revision ID: 020_idempotency_keys
Revises: 019_job_runs
Create Date: 2026-04-08 00:00:00
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "020_idempotency_keys"
down_revision = "019_job_runs"
branch_labels = None
depends_on = None

# pylint: disable=no-member


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", "idempotency_key", name="uq_idempotency_scope_key"),
    )
    op.create_index("ix_idempotency_keys_scope", "idempotency_keys", ["scope"])


def downgrade() -> None:
    op.drop_index("ix_idempotency_keys_scope", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
