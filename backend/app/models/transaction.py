import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Numeric, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
from app.db_types import UuidType


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("tenant_banks.id"), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("customers.id"), nullable=False)
    external_tx_id: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    merchant_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    merchant_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    location_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    tx_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
