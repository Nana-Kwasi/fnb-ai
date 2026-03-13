"""Fraud upgrade: rule_score on fraud_scores; fraud_alerts, customer_behaviour_profile, blacklist, device_fingerprint.

Revision ID: 002
Revises: 001
Create Date: 2026-03-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "fraud_scores",
        sa.Column("rule_score", sa.Numeric(6, 5), nullable=True),
    )

    op.create_table(
        "fraud_alerts",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id"), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), sa.ForeignKey("transactions.id"), nullable=False),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("alert_type", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(20), server_default="HIGH"),
        sa.Column("status", sa.String(20), server_default="OPEN"),
        sa.Column("assigned_to", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_alerts_tenant", "fraud_alerts", ["tenant_id", "created_at"])
    op.create_index("idx_alerts_status", "fraud_alerts", ["tenant_id", "status"])

    op.create_table(
        "customer_behaviour_profile",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id"), nullable=False),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("avg_transaction", sa.Numeric(18, 4), nullable=True),
        sa.Column("max_transaction", sa.Numeric(18, 4), nullable=True),
        sa.Column("usual_location_country", sa.String(2), nullable=True),
        sa.Column("usual_device_id", sa.String(255), nullable=True),
        sa.Column("transaction_frequency_7d", sa.Numeric(10, 2), nullable=True),
        sa.Column("last_updated", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_behaviour_tenant_customer", "customer_behaviour_profile", ["tenant_id", "customer_id"], unique=True)

    op.create_table(
        "blacklist",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id"), nullable=False),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("value", sa.String(512), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_blacklist_tenant_type_value", "blacklist", ["tenant_id", "entity_type", "value"], unique=True)

    op.create_table(
        "device_fingerprint",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id"), nullable=False),
        sa.Column("device_id", sa.String(255), nullable=False),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("device_os", sa.String(100), nullable=True),
        sa.Column("device_browser", sa.String(100), nullable=True),
        sa.Column("ip_address_hash", sa.String(64), nullable=True),
        sa.Column("last_used", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_device_tenant_device", "device_fingerprint", ["tenant_id", "device_id"])
    op.create_index("idx_device_customer", "device_fingerprint", ["tenant_id", "customer_id"])


def downgrade() -> None:
    op.drop_table("device_fingerprint")
    op.drop_table("blacklist")
    op.drop_table("customer_behaviour_profile")
    op.drop_table("fraud_alerts")
    op.drop_column("fraud_scores", "rule_score")
