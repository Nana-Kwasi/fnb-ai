import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.db_types import UuidType


class ModelKpiSnapshot(Base):
    __tablename__ = "model_kpi_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("tenant_banks.id"), nullable=False, index=True)
    model_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    window_days: Mapped[int] = mapped_column(nullable=False, default=30)
    total_scored: Mapped[int] = mapped_column(nullable=False, default=0)
    labeled_count: Mapped[int] = mapped_column(nullable=False, default=0)
    block_rate: Mapped[float] = mapped_column(nullable=False, default=0.0)
    otp_rate: Mapped[float] = mapped_column(nullable=False, default=0.0)
    alert_rate: Mapped[float] = mapped_column(nullable=False, default=0.0)
    precision: Mapped[float | None] = mapped_column(nullable=True)
    recall: Mapped[float | None] = mapped_column(nullable=True)
    fpr: Mapped[float | None] = mapped_column(nullable=True)
    auc: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
