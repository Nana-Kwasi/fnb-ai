import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, DateTime, ForeignKey, LargeBinary, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.db_types import UuidType


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("tenant_banks.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    phone_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    risk_score: Mapped[float] = mapped_column(default=0.0)
    account_count: Mapped[int] = mapped_column(Integer, default=1)
    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = ({"schema": None},)
