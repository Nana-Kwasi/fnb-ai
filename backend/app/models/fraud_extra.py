import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Text, DateTime, ForeignKey
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
