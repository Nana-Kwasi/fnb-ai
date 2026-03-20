"""Transaction fingerprinting: transaction_fingerprints, fingerprint_stats.

Revision ID: 004
Revises: 003
Create Date: 2026-03-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transaction_fingerprints",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id"), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), sa.ForeignKey("transactions.id"), nullable=False),
        sa.Column("fingerprint_id", sa.String(32), nullable=False),
        sa.Column("device_id", sa.String(255), nullable=True),
        sa.Column("ip_address_hash", sa.String(64), nullable=True),
        sa.Column("merchant_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_txn_fp_tenant_fp", "transaction_fingerprints", ["tenant_id", "fingerprint_id"])
    op.create_index("idx_txn_fp_created", "transaction_fingerprints", ["created_at"])

    op.create_table(
        "fingerprint_stats",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id"), nullable=False),
        sa.Column("fingerprint_id", sa.String(32), nullable=False),
        sa.Column("total_transactions", sa.Integer(), server_default="0"),
        sa.Column("fraud_transactions", sa.Integer(), server_default="0"),
        sa.Column("fraud_rate", sa.Float(), server_default="0.0"),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_fingerprint_stats", "fingerprint_stats", ["tenant_id", "fingerprint_id"])
    op.create_index("idx_fp_stats_tenant", "fingerprint_stats", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("fingerprint_stats")
    op.drop_table("transaction_fingerprints")
