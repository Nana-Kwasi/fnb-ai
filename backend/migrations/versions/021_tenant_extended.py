"""tenant extended models: subscription, usage metrics, webhook logs,
notification config, compliance policy, feature flags, SLA config

Revision ID: 021_tenant_extended
Revises: 020_idempotency_keys
Create Date: 2026-04-17 00:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "021_tenant_extended"
down_revision = "020_idempotency_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── tenant_subscriptions ──────────────────────────────────────────────────
    op.create_table(
        "tenant_subscriptions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("plan_tier", sa.String(20), nullable=False, server_default="STARTER"),
        sa.Column("fraud_calls_monthly", sa.Integer, nullable=False, server_default="10000"),
        sa.Column("care_calls_monthly", sa.Integer, nullable=False, server_default="5000"),
        sa.Column("fraud_ring_detection_enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("graph_analysis_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("shadow_mode_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("custom_model_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("rag_knowledge_base_enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("pdf_statements_enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("billing_email", sa.String(320), nullable=True),
        sa.Column("billing_reference", sa.String(100), nullable=True),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("subscription_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_tenant_subscriptions_tenant_id", "tenant_subscriptions", ["tenant_id"])

    # ── tenant_usage_metrics ──────────────────────────────────────────────────
    op.create_table(
        "tenant_usage_metrics",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fraud_score_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("care_chat_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("admin_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("fraud_blocks", sa.Integer, nullable=False, server_default="0"),
        sa.Column("fraud_otp_challenges", sa.Integer, nullable=False, server_default="0"),
        sa.Column("care_escalations", sa.Integer, nullable=False, server_default="0"),
        sa.Column("avg_fraud_latency_ms", sa.Numeric(10, 2), nullable=True),
        sa.Column("avg_care_latency_ms", sa.Numeric(10, 2), nullable=True),
        sa.Column("error_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_tenant_usage_metrics_tenant_period", "tenant_usage_metrics", ["tenant_id", "period_start"])

    # ── tenant_webhook_logs ───────────────────────────────────────────────────
    op.create_table(
        "tenant_webhook_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("target_url", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("http_status_code", sa.Integer, nullable=True),
        sa.Column("response_body", sa.Text, nullable=True),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_tenant_webhook_logs_tenant_status", "tenant_webhook_logs", ["tenant_id", "status"])
    op.create_index("ix_tenant_webhook_logs_next_retry", "tenant_webhook_logs", ["next_retry_at"])

    # ── tenant_notification_configs ───────────────────────────────────────────
    op.create_table(
        "tenant_notification_configs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("fraud_alert_emails", sa.JSON, nullable=True),
        sa.Column("ops_alert_emails", sa.JSON, nullable=True),
        sa.Column("compliance_alert_emails", sa.JSON, nullable=True),
        sa.Column("slack_webhook_url", sa.Text, nullable=True),
        sa.Column("teams_webhook_url", sa.Text, nullable=True),
        sa.Column("sms_alert_numbers", sa.JSON, nullable=True),
        sa.Column("fraud_rate_alert_threshold", sa.Numeric(5, 4), nullable=False, server_default="0.05"),
        sa.Column("block_rate_alert_threshold", sa.Numeric(5, 4), nullable=False, server_default="0.10"),
        sa.Column("fraud_alert_enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("drift_alert_enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("model_rollback_alert_enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("sla_breach_alert_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ── tenant_compliance_policies ────────────────────────────────────────────
    op.create_table(
        "tenant_compliance_policies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("frameworks", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("transaction_retention_days", sa.Integer, nullable=False, server_default="2555"),
        sa.Column("fraud_score_retention_days", sa.Integer, nullable=False, server_default="2555"),
        sa.Column("chat_retention_days", sa.Integer, nullable=False, server_default="365"),
        sa.Column("audit_log_retention_days", sa.Integer, nullable=False, server_default="2555"),
        sa.Column("right_to_erasure_enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("data_portability_enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("field_level_encryption_enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("pii_masking_in_logs", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("explainability_required", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("human_review_on_block", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("last_compliance_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_compliance_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("compliance_officer_email", sa.String(320), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ── tenant_feature_flags ──────────────────────────────────────────────────
    op.create_table(
        "tenant_feature_flags",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("flag_name", sa.String(100), nullable=False),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("flag_config", sa.JSON, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("enabled_by", sa.String(255), nullable=True),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_tenant_feature_flag", "tenant_feature_flags", ["tenant_id", "flag_name"])
    op.create_index("ix_tenant_feature_flags_tenant_id", "tenant_feature_flags", ["tenant_id"])

    # ── tenant_sla_configs ────────────────────────────────────────────────────
    op.create_table(
        "tenant_sla_configs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("fraud_p95_target_ms", sa.Integer, nullable=False, server_default="200"),
        sa.Column("fraud_p99_target_ms", sa.Integer, nullable=False, server_default="500"),
        sa.Column("care_p95_target_ms", sa.Integer, nullable=False, server_default="2000"),
        sa.Column("care_p99_target_ms", sa.Integer, nullable=False, server_default="5000"),
        sa.Column("uptime_target_pct", sa.Numeric(5, 2), nullable=False, server_default="99.9"),
        sa.Column("fraud_sla_breach_count_30d", sa.Integer, nullable=False, server_default="0"),
        sa.Column("care_sla_breach_count_30d", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("tenant_sla_configs")
    op.drop_table("tenant_feature_flags")
    op.drop_table("tenant_compliance_policies")
    op.drop_table("tenant_notification_configs")
    op.drop_table("tenant_webhook_logs")
    op.drop_table("tenant_usage_metrics")
    op.drop_table("tenant_subscriptions")
