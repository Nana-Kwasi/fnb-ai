"""Fraud outcomes, fraud_rules tables and seed default global rules.

Revision ID: 005
Revises: 004
Create Date: 2026-03-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fraud_outcomes",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id"), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), sa.ForeignKey("transactions.id"), nullable=False),
        sa.Column("alert_id", sa.Uuid(), sa.ForeignKey("fraud_alerts.id"), nullable=True),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_fraud_outcomes_tenant", "fraud_outcomes", ["tenant_id"])
    op.create_index("idx_fraud_outcomes_txn", "fraud_outcomes", ["transaction_id"])

    op.create_table(
        "fraud_rules",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id"), nullable=True),
        sa.Column("rule_id", sa.String(64), nullable=False),
        sa.Column("condition_expression", sa.Text(), nullable=False),
        sa.Column("weight", sa.Float(), server_default="0.5"),
        sa.Column("reason_code", sa.String(128), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_fraud_rules_tenant", "fraud_rules", ["tenant_id"])
    op.create_index("idx_fraud_rules_enabled", "fraud_rules", ["enabled"])

    op.execute(
        sa.text("""
            INSERT INTO fraud_rules (id, tenant_id, rule_id, condition_expression, weight, reason_code, enabled)
            VALUES
                (uuid_generate_v4(), NULL, 'velocity_1h', 'txn_count_1h >= velocity_1h_threshold', 0.5, 'Rapid transaction velocity', true),
                (uuid_generate_v4(), NULL, 'new_device_amount', 'is_new_device == 1 and amount >= amount_threshold * 0.2', 0.7, 'New device + large transfer', true),
                (uuid_generate_v4(), NULL, 'high_risk_country', 'location_country in suspicious_countries', 0.8, 'Transaction from high-risk country', true),
                (uuid_generate_v4(), NULL, 'fingerprint_velocity', 'fingerprint_velocity_1h >= 3', 0.7, 'Repeated identical transaction pattern (fingerprint velocity)', true),
                (uuid_generate_v4(), NULL, 'device_ring', 'accounts_seen_for_device_7d >= 5', 0.7, 'Device seen on many accounts in 7d', true)
        """)
    )


def downgrade() -> None:
    op.drop_table("fraud_rules")
    op.drop_table("fraud_outcomes")
