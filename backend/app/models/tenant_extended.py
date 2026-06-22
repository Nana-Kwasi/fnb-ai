import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, Numeric, Text, DateTime, ForeignKey, JSON, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.db_types import UuidType
import enum


class PlanTier(str, enum.Enum):
    FREE = "FREE"
    STARTER = "STARTER"
    PROFESSIONAL = "PROFESSIONAL"
    ENTERPRISE = "ENTERPRISE"


class WebhookStatus(str, enum.Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"


class TenantSubscription(Base):
    """Billing plan, feature flags, and quota controls per tenant."""
    __tablename__ = "tenant_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UuidType(), ForeignKey("tenant_banks.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    plan_tier: Mapped[str] = mapped_column(String(20), nullable=False, default=PlanTier.STARTER)
    # Monthly API call quotas (-1 = unlimited)
    fraud_calls_monthly: Mapped[int] = mapped_column(Integer, default=10_000)
    care_calls_monthly: Mapped[int] = mapped_column(Integer, default=5_000)
    # Feature flags
    fraud_ring_detection_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    graph_analysis_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    shadow_mode_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    custom_model_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    rag_knowledge_base_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    pdf_statements_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Billing
    billing_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    billing_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    subscription_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class TenantUsageMetrics(Base):
    """Hourly API usage snapshots per tenant for billing and quota enforcement."""
    __tablename__ = "tenant_usage_metrics"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UuidType(), ForeignKey("tenant_banks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Period covered (hour bucket: truncated to hour)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Call counts
    fraud_score_calls: Mapped[int] = mapped_column(Integer, default=0)
    care_chat_calls: Mapped[int] = mapped_column(Integer, default=0)
    admin_calls: Mapped[int] = mapped_column(Integer, default=0)
    # Outcome counters
    fraud_blocks: Mapped[int] = mapped_column(Integer, default=0)
    fraud_otp_challenges: Mapped[int] = mapped_column(Integer, default=0)
    care_escalations: Mapped[int] = mapped_column(Integer, default=0)
    # Performance
    avg_fraud_latency_ms: Mapped[float | None] = mapped_column(nullable=True)
    avg_care_latency_ms: Mapped[float | None] = mapped_column(nullable=True)
    # Error counts
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class TenantWebhookLog(Base):
    """Delivery tracking for outbound webhook events to tenant endpoints."""
    __tablename__ = "tenant_webhook_logs"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UuidType(), ForeignKey("tenant_banks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=WebhookStatus.PENDING)
    http_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class TenantNotificationConfig(Base):
    """Alert routing config: where to send fraud alerts, SLA breaches, and system events."""
    __tablename__ = "tenant_notification_configs"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UuidType(), ForeignKey("tenant_banks.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # Email channels
    fraud_alert_emails: Mapped[list | None] = mapped_column(JSON, nullable=True)
    ops_alert_emails: Mapped[list | None] = mapped_column(JSON, nullable=True)
    compliance_alert_emails: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Slack/Teams webhooks
    slack_webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    teams_webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # SMS (Twilio-compatible)
    sms_alert_numbers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Thresholds that trigger alerts
    fraud_rate_alert_threshold: Mapped[float] = mapped_column(Numeric(5, 4), default=0.05)
    block_rate_alert_threshold: Mapped[float] = mapped_column(Numeric(5, 4), default=0.10)
    # Feature switches
    fraud_alert_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    drift_alert_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    model_rollback_alert_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sla_breach_alert_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class TenantCompliancePolicy(Base):
    """Regulatory and data governance settings per tenant (GDPR, POPIA, PCI-DSS, etc.)."""
    __tablename__ = "tenant_compliance_policies"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UuidType(), ForeignKey("tenant_banks.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # Regulatory frameworks this tenant must comply with
    frameworks: Mapped[list] = mapped_column(JSON, default=list)  # ["GDPR", "POPIA", "PCI_DSS"]
    # Data retention (days, 0 = keep forever)
    transaction_retention_days: Mapped[int] = mapped_column(Integer, default=2555)  # 7 years
    fraud_score_retention_days: Mapped[int] = mapped_column(Integer, default=2555)
    chat_retention_days: Mapped[int] = mapped_column(Integer, default=365)
    audit_log_retention_days: Mapped[int] = mapped_column(Integer, default=2555)
    # Customer data rights
    right_to_erasure_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    data_portability_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Encryption settings
    field_level_encryption_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    pii_masking_in_logs: Mapped[bool] = mapped_column(Boolean, default=True)
    # Model explainability (required by some regulators for credit/fraud decisions)
    explainability_required: Mapped[bool] = mapped_column(Boolean, default=True)
    human_review_on_block: Mapped[bool] = mapped_column(Boolean, default=False)
    # Audit
    last_compliance_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_compliance_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    compliance_officer_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class TenantFeatureFlag(Base):
    """Individual feature flag overrides per tenant (for staged rollouts and A/B testing)."""
    __tablename__ = "tenant_feature_flags"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UuidType(), ForeignKey("tenant_banks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    flag_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Optional JSON payload for flags that carry config (e.g. {"model": "gpt-4o", "max_tokens": 512})
    flag_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        {"comment": "One row per (tenant, flag_name). Use unique constraint in migration."},
    )


class TenantSLAConfig(Base):
    """SLA targets for fraud scoring and care response latency per tenant."""
    __tablename__ = "tenant_sla_configs"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UuidType(), ForeignKey("tenant_banks.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # Latency targets (milliseconds)
    fraud_p95_target_ms: Mapped[int] = mapped_column(Integer, default=200)
    fraud_p99_target_ms: Mapped[int] = mapped_column(Integer, default=500)
    care_p95_target_ms: Mapped[int] = mapped_column(Integer, default=2000)
    care_p99_target_ms: Mapped[int] = mapped_column(Integer, default=5000)
    # Uptime target (percentage, e.g. 99.9)
    uptime_target_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=99.9)
    # Breach tracking
    fraud_sla_breach_count_30d: Mapped[int] = mapped_column(Integer, default=0)
    care_sla_breach_count_30d: Mapped[int] = mapped_column(Integer, default=0)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
