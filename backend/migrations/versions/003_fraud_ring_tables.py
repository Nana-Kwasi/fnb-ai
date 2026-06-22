"""Fraud ring: device_account_map, ip_account_map, merchant_risk, account_connections.

Revision ID: 003
Revises: 002
Create Date: 2026-03-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "device_account_map",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id"), nullable=False),
        sa.Column("device_id", sa.String(255), nullable=False),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_unique_constraint("uq_device_account", "device_account_map", ["tenant_id", "device_id", "customer_id"])
    op.create_index("idx_device_account_tenant_device", "device_account_map", ["tenant_id", "device_id"])
    op.create_index("idx_device_account_last_seen", "device_account_map", ["last_seen"])

    op.create_table(
        "ip_account_map",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id"), nullable=False),
        sa.Column("ip_address", sa.String(64), nullable=False),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_unique_constraint("uq_ip_account", "ip_account_map", ["tenant_id", "ip_address", "customer_id"])
    op.create_index("idx_ip_account_tenant_ip", "ip_account_map", ["tenant_id", "ip_address"])
    op.create_index("idx_ip_account_last_seen", "ip_account_map", ["last_seen"])

    op.create_table(
        "merchant_risk",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id"), nullable=False),
        sa.Column("merchant_id", sa.String(255), nullable=False),
        sa.Column("total_transactions", sa.Integer(), server_default="0"),
        sa.Column("fraud_transactions", sa.Integer(), server_default="0"),
        sa.Column("fraud_rate", sa.Float(), server_default="0.0"),
        sa.Column("last_updated", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_merchant_risk", "merchant_risk", ["tenant_id", "merchant_id"])
    op.create_index("idx_merchant_risk_tenant", "merchant_risk", ["tenant_id"])

    op.create_table(
        "account_connections",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id"), nullable=False),
        sa.Column("source_customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("destination_customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("transaction_count", sa.Integer(), server_default="0"),
        sa.Column("last_transaction", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint("uq_account_connection", "account_connections", ["tenant_id", "source_customer_id", "destination_customer_id"])
    op.create_index("idx_account_connections_tenant", "account_connections", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("account_connections")
    op.drop_table("merchant_risk")
    op.drop_table("ip_account_map")
    op.drop_table("device_account_map")
