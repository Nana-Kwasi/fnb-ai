import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Boolean, Integer, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
from app.db_types import UuidType, StringArrayType


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("tenant_banks.id"), nullable=False)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UuidType(), ForeignKey("customers.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    intent_history: Mapped[list | None] = mapped_column(StringArrayType(), nullable=True)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UuidType(), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("chat_sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
