import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, Numeric, Text, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.db_types import UuidType


class TenantBank(Base):
    __tablename__ = "tenant_banks"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    api_key_prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    fraud_threshold: Mapped[float] = mapped_column(Numeric(4, 3), default=0.75)
    care_model: Mapped[str] = mapped_column(String(50), default="phi3")
    tone_config: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    rate_limit: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
