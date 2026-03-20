import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, Text, DateTime, ForeignKey, JSON, Boolean, Float, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.db_types import UuidType


class FraudAlert(Base):
    __tablename__ = "fraud_alerts"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("tenant_banks.id"), nullable=False)
    transaction_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("transactions.id"), nullable=False)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UuidType(), ForeignKey("customers.id"), nullable=True)
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="HIGH")
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(UuidType(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class CustomerBehaviourProfile(Base):
    __tablename__ = "customer_behaviour_profile"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("tenant_banks.id"), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("customers.id"), nullable=False)
    avg_transaction: Mapped[Decimal | None] = mapped_column(nullable=True)
    max_transaction: Mapped[Decimal | None] = mapped_column(nullable=True)
    usual_location_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    usual_device_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transaction_frequency_7d: Mapped[Decimal | None] = mapped_column(nullable=True)
    # JSON histograms / profiles for richer behavioural modelling
    hour_histogram: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    country_histogram: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    channel_profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    velocity_baseline_by_channel: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    median_transaction: Mapped[Decimal | None] = mapped_column(nullable=True)
    iqr_transaction: Mapped[Decimal | None] = mapped_column(nullable=True)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class Blacklist(Base):
    __tablename__ = "blacklist"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("tenant_banks.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    value: Mapped[str] = mapped_column(String(512), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class DeviceFingerprint(Base):
    __tablename__ = "device_fingerprint"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("tenant_banks.id"), nullable=False)
    device_id: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UuidType(), ForeignKey("customers.id"), nullable=True)
    device_os: Mapped[str | None] = mapped_column(String(100), nullable=True)
    device_browser: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ip_address_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_used: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class FraudOutcome(Base):
    """
    Analyst / chargeback feedback on a fraud alert or transaction.
    Used as supervised labels for model training.
    """

    __tablename__ = "fraud_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("tenant_banks.id"), nullable=False)
    transaction_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("transactions.id"), nullable=False)
    alert_id: Mapped[uuid.UUID | None] = mapped_column(UuidType(), ForeignKey("fraud_alerts.id"), nullable=True)
    # CONFIRMED_FRAUD, FALSE_POSITIVE, CONFIRMED_LEGIT
    classification: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)  # e.g. CHARGEBACK, ANALYST, INVESTIGATION
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class FraudRule(Base):
    """
    Tenant-configurable fraud rule.

    Example condition_expression:
        "amount > 10000 and is_new_device == 1 and location_country in suspicious_countries"
    """

    __tablename__ = "fraud_rules"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UuidType(), ForeignKey("tenant_banks.id"), nullable=True)
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    condition_expression: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=0.5)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class DeviceAccountMap(Base):
    """Account–device usage for fraud ring analysis. One row per (tenant, device_id, customer)."""
    __tablename__ = "device_account_map"
    __table_args__ = (UniqueConstraint("tenant_id", "device_id", "customer_id", name="uq_device_account"),)

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("tenant_banks.id"), nullable=False)
    device_id: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("customers.id"), nullable=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IPAccountMap(Base):
    """Account–IP usage for fraud ring analysis."""
    __tablename__ = "ip_account_map"
    __table_args__ = (UniqueConstraint("tenant_id", "ip_address", "customer_id", name="uq_ip_account"),)

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("tenant_banks.id"), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("customers.id"), nullable=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MerchantRisk(Base):
    """Per-tenant merchant fraud stats for ring/merchant-hub detection."""
    __tablename__ = "merchant_risk"
    __table_args__ = (UniqueConstraint("tenant_id", "merchant_id", name="uq_merchant_risk"),)

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("tenant_banks.id"), nullable=False)
    merchant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    total_transactions: Mapped[int] = mapped_column(default=0)
    fraud_transactions: Mapped[int] = mapped_column(default=0)
    fraud_rate: Mapped[float] = mapped_column(Float, default=0.0)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class AccountConnection(Base):
    """P2P / transfer links for circular-flow detection. Populated when transfer/counterparty data exists."""
    __tablename__ = "account_connections"
    __table_args__ = (UniqueConstraint("tenant_id", "source_customer_id", "destination_customer_id", name="uq_account_connection"),)

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("tenant_banks.id"), nullable=False)
    source_customer_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("customers.id"), nullable=False)
    destination_customer_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("customers.id"), nullable=False)
    transaction_count: Mapped[int] = mapped_column(default=0)
    last_transaction: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TransactionFingerprint(Base):
    """Links each transaction to its pattern fingerprint for repeat/bot detection."""
    __tablename__ = "transaction_fingerprints"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("tenant_banks.id"), nullable=False)
    transaction_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("transactions.id"), nullable=False)
    fingerprint_id: Mapped[str] = mapped_column(String(32), nullable=False)
    device_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    merchant_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class FingerprintStats(Base):
    """Per-fingerprint aggregate: total txns, fraud count, fraud rate. Used as features."""
    __tablename__ = "fingerprint_stats"
    __table_args__ = (UniqueConstraint("tenant_id", "fingerprint_id", name="uq_fingerprint_stats"),)

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("tenant_banks.id"), nullable=False)
    fingerprint_id: Mapped[str] = mapped_column(String(32), nullable=False)
    total_transactions: Mapped[int] = mapped_column(default=0)
    fraud_transactions: Mapped[int] = mapped_column(default=0)
    fraud_rate: Mapped[float] = mapped_column(Float, default=0.0)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
