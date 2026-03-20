import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
from app.db_types import UuidType, StringArrayType


class FraudScore(Base):
    __tablename__ = "fraud_scores"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("tenant_banks.id"), nullable=False)
    transaction_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("transactions.id"), nullable=False)
    lgbm_score: Mapped[Decimal] = mapped_column(nullable=False)
    isolation_score: Mapped[Decimal | None] = mapped_column(nullable=True)
    rule_score: Mapped[Decimal | None] = mapped_column(nullable=True)
    ensemble_score: Mapped[Decimal] = mapped_column(nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[str] = mapped_column(String(6), nullable=False)
    shap_values: Mapped[dict] = mapped_column(JSON, nullable=False)
    reason_codes: Mapped[list] = mapped_column(StringArrayType(), nullable=False)
    feature_vector: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model_version: Mapped[str] = mapped_column(String(20), nullable=False)
    processing_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
