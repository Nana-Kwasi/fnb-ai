import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.db_types import UuidType


class ModelRegistry(Base):
    __tablename__ = "model_registry"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    model_type: Mapped[str] = mapped_column(String(16), nullable=False)  # fraud|care
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UuidType(), ForeignKey("tenant_banks.id"), nullable=True, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    feature_contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    mapper_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="shadow")  # shadow|active|rollback|disabled
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("model_type", "tenant_id", "version", name="uq_model_registry_model_tenant_version"),
    )


class TenantMapper(Base):
    __tablename__ = "tenant_mappers"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("tenant_banks.id"), nullable=False, index=True)
    model_type: Mapped[str] = mapped_column(String(16), nullable=False)  # fraud|care
    mapper_version: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    mapping_json: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "model_type", "mapper_version", name="uq_tenant_mappers_tenant_model_mapper"),
    )


class InferenceTrace(Base):
    __tablename__ = "inference_trace"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("tenant_banks.id"), nullable=False, index=True)
    model_type: Mapped[str] = mapped_column(String(16), nullable=False)  # fraud|care
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    mapper_version: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    processing_ms: Mapped[int | None] = mapped_column(nullable=True)
    trace_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
